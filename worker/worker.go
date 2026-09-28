package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	urlpkg "net/url"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

var (
	redisURL         = getEnv("REDIS_URL", "redis://redis:6379/0")
	concurrency      = getEnvInt("WORKER_CONCURRENCY", 4)
	runnerPath       = getEnv("RUNNER_PATH", "/usr/local/bin/worker/runner.py")
	qdrantURL        = getEnv("QDRANT_URL", "http://qdrant:6333")
	qdrantCollection = getEnv("QDRANT_COLLECTION", "product_vectors")
	embeddingURL     = getEnv("EMBEDDING_URL", "http://embedding:8080/embeddings")
	qdrantAPIKey     = getEnv("QDRANT_API_KEY", "")
	proxyListEnv     = getEnv("PROXY_LIST", "")            // comma separated proxies e.g. http://user:pass@host:port
	proxyStickyTTL   = getEnvInt("PROXY_STICKY_TTL", 1800) // seconds to keep sticky mapping
)

// ProxyPool manages a small pool of proxies and sticky mappings per key.
type ProxyPool struct {
	proxies []string
	mu      sync.Mutex
	// sticky maps a key (e.g., host) to proxy index and expiry
	sticky map[string]struct {
		idx int
		exp int64
	}
	rr int
}

func NewProxyPool(list string) *ProxyPool {
	p := &ProxyPool{sticky: make(map[string]struct {
		idx int
		exp int64
	})}
	if list == "" {
		return p
	}
	parts := []string{}
	for _, part := range strings.Split(list, ",") {
		s := strings.TrimSpace(part)
		if s != "" {
			parts = append(parts, s)
		}
	}
	p.proxies = parts
	// seed rand
	rand.Seed(time.Now().UnixNano())
	return p
}

// getProxyForKey returns a proxy URL for a given key. If no proxies configured returns empty string.
func (p *ProxyPool) getProxyForKey(key string) string {
	if p == nil {
		return ""
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if len(p.proxies) == 0 {
		return ""
	}
	now := time.Now().Unix()
	if st, ok := p.sticky[key]; ok {
		if st.exp > now && st.idx >= 0 && st.idx < len(p.proxies) {
			return p.proxies[st.idx]
		}
		// expired
		delete(p.sticky, key)
	}
	// pick next by round-robin with randomness
	idx := p.rr % len(p.proxies)
	// add small jitter
	idx = (idx + rand.Intn(len(p.proxies))) % len(p.proxies)
	p.rr = (p.rr + 1) % len(p.proxies)
	// store sticky mapping
	p.sticky[key] = struct {
		idx int
		exp int64
	}{idx: idx, exp: time.Now().Unix() + int64(proxyStickyTTL)}
	return p.proxies[idx]
}

// global proxy pool instance (initialized in main)
var proxyPool *ProxyPool

func getEnv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getEnvInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if i, err := strconv.Atoi(v); err == nil {
			return i
		}
	}
	return def
}

// urlpkgParse is a tiny wrapper to avoid accidental name clash with local vars.
func urlpkgParse(s string) (*urlpkg.URL, error) {
	return urlpkg.Parse(s)
}

func processURL(ctx context.Context, client *redis.Client, url string) {
	fmt.Println("Worker: procesando", url)
	// Ejecutar runner Python con JSON stdin
	payload := map[string]string{"url": url}
	b, _ := json.Marshal(payload)
	// prepare environment for runner, possibly binding a proxy for sticky sessions per host
	cmd := exec.CommandContext(ctx, "python3", runnerPath)
	// determine proxy for this URL
	var proxyForThis string
	if proxyPool != nil {
		// use host as sticky key
		if u, err := urlpkgParse(url); err == nil {
			proxyForThis = proxyPool.getProxyForKey(u.Host)
		}
	}
	if proxyForThis != "" {
		// set environment variables for the runner process
		env := os.Environ()
		// push both HTTP_PROXY and HTTPS_PROXY to support different transports
		env = append(env, "HTTP_PROXY="+proxyForThis, "http_proxy="+proxyForThis)
		env = append(env, "HTTPS_PROXY="+proxyForThis, "https_proxy="+proxyForThis)
		cmd.Env = env
	}
	// for debugging, expose proxy used via stdout/stderr
	if proxyForThis != "" {
		fmt.Println("Using proxy for host:", proxyForThis)
	}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		fmt.Println("stdin pipe error:", err)
		return
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		fmt.Println("stdout pipe error:", err)
		return
	}
	if err := cmd.Start(); err != nil {
		fmt.Println("runner start error:", err)
		return
	}
	stdin.Write(b)
	stdin.Close()
	var resp map[string]interface{}
	dec := json.NewDecoder(stdout)
	if err := dec.Decode(&resp); err != nil {
		fmt.Println("runner decode error:", err)
		_ = cmd.Wait()
		return
	}
	_ = cmd.Wait()

	// actualizar Redis según meta_updates
	metaKey := "product:meta:" + url
	now := time.Now().Unix()
	freq := 48 * 3600
	if fstr, err := client.HGet(ctx, metaKey, "frequency").Result(); err == nil {
		if i, err := strconv.Atoi(fstr); err == nil && i > 0 {
			freq = i
		}
	}
	// aplicar updates retornados por el runner
	if mu, ok := resp["meta_updates"].(map[string]interface{}); ok {
		mapping := make(map[string]interface{})
		for k, v := range mu {
			mapping[k] = fmt.Sprintf("%v", v)
		}
		// ensure last_scraped_at
		if _, ok := mapping["last_scraped_at"]; !ok {
			mapping["last_scraped_at"] = strconv.FormatInt(now, 10)
		}
		client.HSet(ctx, metaKey, mapping)
	} else {
		client.HSet(ctx, metaKey, "last_scraped_at", strconv.FormatInt(now, 10))
	}
	// reprogramar
	client.ZAdd(ctx, "schedule:urls", redis.Z{Score: float64(now + int64(freq)), Member: url})

	// Si runner devolvió producto, intentar matching en Qdrant
	if prodObj, ok := resp["product"].(map[string]interface{}); ok {
		go func() {
			matchAndEnqueue(ctx, client, url, prodObj)
		}()
	}
}

// build canonical string from product fields
func canonicalString(product map[string]interface{}) string {
	brand := ""
	if b, ok := product["brand"].(string); ok {
		brand = b
	}
	name := ""
	if n, ok := product["name"].(string); ok {
		name = n
	}
	// try to remove brand from name
	cleanName := name
	if brand != "" {
		// naive case-insensitive removal
		cleanName = strings.TrimSpace(strings.Replace(strings.ToLower(name), strings.ToLower(brand), "", 1))
	}
	// gather attributes
	attrsKeys := []string{"ram", "memory", "storage", "almacenamiento", "capacidad", "color", "size", "modelo", "model"}
	parts := []string{}
	if brand != "" {
		parts = append(parts, brand)
	}
	if cleanName != "" {
		parts = append(parts, cleanName)
	}
	for _, key := range attrsKeys {
		if v, ok := product[key]; ok {
			if s, ok := v.(string); ok && s != "" {
				parts = append(parts, s)
			}
		}
	}
	return strings.Join(parts, " ")
}

// getEmbedding posts text to embedding service and returns vector
func getEmbedding(text string) ([]float64, error) {
	bodyMap := map[string]string{"text": text}
	b, _ := json.Marshal(bodyMap)
	client := &http.Client{Timeout: 8 * time.Second}
	// allow proxy env vars from process to be respected by http.Client
	resp, err := client.Post(embeddingURL, "application/json", bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	var out map[string]interface{}
	if err := json.Unmarshal(data, &out); err != nil {
		return nil, err
	}
	// expect out["embedding"] as []float64
	if arr, ok := out["embedding"].([]interface{}); ok {
		vec := make([]float64, 0, len(arr))
		for _, v := range arr {
			if f, ok := v.(float64); ok {
				vec = append(vec, f)
			}
		}
		return vec, nil
	}
	return nil, fmt.Errorf("invalid embedding response")
}

// qdrantSearch queries qdrant for similar vectors with payload filter
func qdrantSearch(vector []float64, brand, category, store string) ([]map[string]interface{}, error) {
	url := fmt.Sprintf("%s/collections/%s/points/search", qdrantURL, qdrantCollection)
	filter := map[string]interface{}{
		"must": []interface{}{
			map[string]interface{}{"key": "brand", "match": map[string]interface{}{"value": brand}},
			map[string]interface{}{"key": "category_normalized", "match": map[string]interface{}{"value": category}},
		},
		"must_not": []interface{}{
			map[string]interface{}{"key": "store_name", "match": map[string]interface{}{"value": store}},
		},
	}
	body := map[string]interface{}{
		"vector":       vector,
		"limit":        5,
		"with_payload": true,
		"filter":       filter,
	}
	b, _ := json.Marshal(body)
	req, _ := http.NewRequest("POST", url, bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	if qdrantAPIKey != "" {
		req.Header.Set("api-key", qdrantAPIKey)
	}
	client := &http.Client{Timeout: 6 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	var out map[string]interface{}
	if err := json.Unmarshal(data, &out); err != nil {
		return nil, err
	}
	// Qdrant may return 'result' or 'data' depending on version
	resArr := []map[string]interface{}{}
	if r, ok := out["result"].([]interface{}); ok {
		for _, item := range r {
			if m, ok := item.(map[string]interface{}); ok {
				resArr = append(resArr, m)
			}
		}
	} else if r, ok := out["data"].([]interface{}); ok {
		for _, item := range r {
			if m, ok := item.(map[string]interface{}); ok {
				resArr = append(resArr, m)
			}
		}
	}
	return resArr, nil
}

// matchAndEnqueue performs Qdrant matching and enqueues actions in Redis lists
func matchAndEnqueue(ctx context.Context, client *redis.Client, url string, product map[string]interface{}) {
	metaKey := "product:meta:" + url
	// extract fields
	store := ""
	if s, ok := product["store"].(string); ok {
		store = s
	}
	brand := ""
	if b, ok := product["brand"].(string); ok {
		brand = strings.ToLower(b)
	}
	category := ""
	if c, ok := product["catalog_category"].(string); ok {
		category = strings.ToLower(c)
	}
	text := canonicalString(product)
	if text == "" || brand == "" || category == "" {
		client.HSet(ctx, metaKey, map[string]interface{}{"match_action": "skipped", "match_reason": "missing_fields"})
		return
	}
	vec, err := getEmbedding(text)
	if err != nil {
		client.HSet(ctx, metaKey, map[string]interface{}{"match_action": "error", "match_reason": "embed_error"})
		return
	}
	results, err := qdrantSearch(vec, brand, category, store)
	if err != nil {
		client.HSet(ctx, metaKey, map[string]interface{}{"match_action": "error", "match_reason": "qdrant_error"})
		return
	}
	// evaluate top result
	if len(results) == 0 {
		// new product: enqueue create with embedding
		payload := map[string]interface{}{"url": url, "product": product}
		data, _ := json.Marshal(payload)
		client.RPush(ctx, "product:create_queue", string(data))
		client.HSet(ctx, metaKey, map[string]interface{}{"match_action": "new"})
		return
	}
	// find top by score
	top := results[0]
	score := 0.0
	if s, ok := top["score"].(float64); ok {
		score = s
	}
	payload := top["payload"]
	masterID := ""
	if pmap, ok := payload.(map[string]interface{}); ok {
		if mid, ok := pmap["master_product_id"].(string); ok {
			masterID = mid
		}
	}
	client.HSet(ctx, metaKey, map[string]interface{}{"match_score": fmt.Sprintf("%f", score), "master_product_id": masterID})
	if score >= 0.95 {
		// linked
		client.RPush(ctx, "product:link_queue", fmt.Sprintf("%s|%s", masterID, url))
		client.HSet(ctx, metaKey, map[string]interface{}{"match_action": "linked"})
	} else if score >= 0.85 {
		// possible variant: send to review
		payload := map[string]interface{}{"url": url, "product": product, "candidate": top}
		data, _ := json.Marshal(payload)
		client.RPush(ctx, "product:review_queue", string(data))
		client.HSet(ctx, metaKey, map[string]interface{}{"match_action": "review"})
	} else {
		// new
		payload := map[string]interface{}{"url": url, "product": product}
		data, _ := json.Marshal(payload)
		client.RPush(ctx, "product:create_queue", string(data))
		client.HSet(ctx, metaKey, map[string]interface{}{"match_action": "new"})
	}
}

func workerLoop(ctx context.Context, wg *sync.WaitGroup, client *redis.Client, id int) {
	defer wg.Done()
	for {
		select {
		case <-ctx.Done():
			return
		default:
			now := time.Now().Unix()
			res, err := client.ZPopMin(ctx, "schedule:urls", 1).Result()
			if err != nil {
				fmt.Println("Redis error:", err)
				time.Sleep(2 * time.Second)
				continue
			}
			if len(res) == 0 || int64(res[0].Score) > now {
				time.Sleep(1 * time.Second)
				continue
			}
			url := fmt.Sprintf("%v", res[0].Member)
			processURL(ctx, client, url)
		}
	}
}

func main() {
	ctx := context.Background()
	// initialize proxy pool early so TEST_PROXY_MODE can use it
	proxyPool = NewProxyPool(proxyListEnv)

	// test mode: run one URL through the runner without connecting to Redis
	if getEnv("TEST_PROXY_MODE", "") == "1" {
		testURL := getEnv("TEST_PROXY_URL", "http://example.com/test-product")
		testRunURL(ctx, testURL)
		return
	}

	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		fmt.Println("Invalid REDIS_URL", err)
		os.Exit(1)
	}
	client := redis.NewClient(opt)
	defer client.Close()
	ctxBg, cancel := context.WithCancel(ctx)
	var wg sync.WaitGroup
	for i := 0; i < concurrency; i++ {
		wg.Add(1)
		go workerLoop(ctxBg, &wg, client, i)
	}
	// wait for termination signal
	sig := make(chan os.Signal, 1)
	<-sig
	cancel()
	wg.Wait()
}

// testRunURL runs the configured runner once for a test URL without touching Redis.
func testRunURL(ctx context.Context, testURL string) {
	fmt.Println("TEST MODE: running single URL through runner ->", testURL)
	payload := map[string]string{"url": testURL}
	b, _ := json.Marshal(payload)
	cmd := exec.CommandContext(ctx, "python3", runnerPath)
	var proxyForThis string
	if proxyPool != nil {
		if u, err := urlpkgParse(testURL); err == nil {
			proxyForThis = proxyPool.getProxyForKey(u.Host)
		}
	}
	if proxyForThis != "" {
		env := os.Environ()
		env = append(env, "HTTP_PROXY="+proxyForThis, "http_proxy="+proxyForThis)
		env = append(env, "HTTPS_PROXY="+proxyForThis, "https_proxy="+proxyForThis)
		cmd.Env = env
		fmt.Println("Using proxy for host:", proxyForThis)
	} else {
		fmt.Println("No proxy configured; running without proxy")
	}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		fmt.Println("stdin pipe error:", err)
		return
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		fmt.Println("stdout pipe error:", err)
		return
	}
	if err := cmd.Start(); err != nil {
		fmt.Println("runner start error:", err)
		return
	}
	stdin.Write(b)
	stdin.Close()
	var resp map[string]interface{}
	dec := json.NewDecoder(stdout)
	if err := dec.Decode(&resp); err != nil {
		fmt.Println("runner decode error:", err)
		_ = cmd.Wait()
		return
	}
	_ = cmd.Wait()
	outB, _ := json.MarshalIndent(resp, "", "  ")
	fmt.Println("Runner response:")
	fmt.Println(string(outB))
}
