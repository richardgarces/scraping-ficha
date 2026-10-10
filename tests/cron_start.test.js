const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

function loadCron(fetch) {
  const source = fs.readFileSync("retail/web/static/cron.js", "utf8");
  const context = vm.createContext({
    $: () => null,
    document: { addEventListener() {} },
    fetch,
    notices: [],
    refreshes: 0,
  });
  // Las funciones se prueban antes de la carga inicial de la página.
  vm.runInContext(source.slice(0, source.lastIndexOf("\nrefresh().catch(")), context);
  vm.runInContext(`
    flash = (message, ok = true) => notices.push([message, ok]);
    refresh = async () => { refreshes += 1; };
  `, context);
  return context;
}

const group = { id: "retail", title: "Retail", status: "idle", store_count: 10 };
const button = () => ({ dataset: { startGroup: "retail" }, disabled: false, textContent: "Iniciar ahora" });

test("solo los grupos en espera y con tiendas ofrecen iniciar", () => {
  const cron = loadCron();
  assert.match(cron.groupStatusCell(group), /En espera/);
  const idle = cron.groupActionsCell(group, false);
  assert.match(idle, /Iniciar ahora/);
  assert.match(idle, /data-start-group="retail"/);
  assert.doesNotMatch(idle, / disabled/);
  assert.doesNotMatch(
    cron.groupActionsCell({
      ...group,
      status: "done",
      last_run: { processed: 100, items: 100 },
    }, false),
    /data-start-group/,
  );
  for (const status of ["running", "paused"]) {
    const cell = cron.groupActionsCell({ ...group, status, progress: { phase: "products" } }, false);
    assert.match(cell, /data-stop-group="retail"/);
    assert.match(cell, /Detener/);
    assert.doesNotMatch(cell, /data-start-group/);
  }
  const stopping = cron.groupActionsCell({ ...group, status: "running", progress: { phase: "stopping" } }, false);
  assert.match(stopping, /Deteniendo/);
  assert.match(stopping, / disabled/);
  assert.doesNotMatch(cron.groupActionsCell({ ...group, store_count: 0 }, false), /data-start-group/);
  assert.match(cron.groupActionsCell(group, true), / disabled/);
  assert.match(cron.groupActionsCell(group, true), /Reanuda las corridas/);
});

test("estados desconocidos se tratan como en espera para iniciar", () => {
  const cron = loadCron();
  assert.match(cron.groupStatusCell({ ...group, status: "scheduled" }), /En espera/);
  const actions = cron.groupActionsCell({ ...group, status: "scheduled" }, false);
  assert.match(actions, /Iniciar ahora/);
  assert.match(cron.groupActionsCell({ ...group, store_count: "6" }, false), /Iniciar ahora/);
});

test("un grupo fallido ofrece continuar y reiniciar", () => {
  const cron = loadCron();
  const failed = cron.groupActionsCell({
    ...group,
    status: "failed",
    last_run: { processed: 239, items: 22490, last_error: "Corrida interrumpida" },
  }, false);
  assert.match(failed, /data-start-mode="continue"/);
  assert.match(failed, /Continuar/);
  assert.match(failed, /data-start-mode="restart"/);
  assert.match(failed, /Reiniciar/);
  const empty = cron.groupActionsCell({
    ...group,
    status: "failed",
    last_run: { processed: 0, items: 100 },
  }, false);
  assert.doesNotMatch(empty, /data-start-mode="continue"/);
  assert.match(empty, /data-start-mode="restart"/);
  const stopped = cron.groupActionsCell({
    ...group,
    status: "stopped",
    last_run: { processed: 12, items: 40 },
  }, false);
  assert.match(stopped, /Continuar/);
  assert.match(stopped, /Reiniciar/);
});

test("un grupo interrumpido (deploy) muestra badge y Continuar", () => {
  const cron = loadCron();
  assert.match(cron.groupStatusCell({ ...group, status: "interrupted" }), /Interrumpido/);
  const interrupted = cron.groupActionsCell({
    ...group,
    status: "interrupted",
    last_run: { processed: 50, items: 200, last_error: "deploy/SIGTERM" },
  }, false);
  assert.match(interrupted, /data-start-mode="continue"/);
  assert.match(interrupted, /Continuar/);
  assert.match(interrupted, /Reiniciar/);
});

test("parcial hoy (presupuesto) ofrece Continuar; completo no", () => {
  const cron = loadCron();
  assert.match(cron.groupStatusCell({ ...group, status: "partial" }), /Parcial hoy/);
  const partial = cron.groupActionsCell({
    ...group,
    status: "partial",
    can_continue: true,
    last_run: { processed: 1778, items: 22499, budget_exhausted: true },
  }, false);
  assert.match(partial, /data-start-mode="continue"/);
  assert.match(partial, /Continuar/);
  assert.match(partial, /data-start-mode="restart"/);
  const pausedPartial = cron.groupActionsCell({
    ...group,
    status: "partial",
    can_continue: true,
    last_run: { processed: 480, items: 1292, budget_exhausted: true },
  }, true);
  assert.match(pausedPartial, / disabled/);
  assert.match(pausedPartial, /Reanuda las corridas/);
  const complete = cron.groupActionsCell({
    ...group,
    status: "done",
    last_run: { processed: 22499, items: 22499, budget_exhausted: false },
  }, false);
  assert.doesNotMatch(complete, /data-start-mode="continue"/);
  assert.doesNotMatch(complete, /Continuar/);
});

test("doble clic y redibujado no duplican la solicitud", async () => {
  let resolve;
  const pending = new Promise((done) => { resolve = done; });
  const calls = [];
  const cron = loadCron((url, options) => { calls.push([url, options.method, options.body]); return pending; });
  const firstButton = button();
  const first = cron.startGroup(firstButton);
  assert.equal(firstButton.disabled, true);
  assert.equal(firstButton.textContent, "Iniciando…");
  assert.match(cron.groupActionsCell(group, false), / disabled/);
  await cron.startGroup(button());
  assert.deepEqual(calls, [["/api/admin/cron-batches/retail/start", "POST", undefined]]);
  resolve({ status: 202, ok: true, json: async () => ({ message: "Corrida iniciada para Retail." }) });
  await first;
  assert.equal(cron.notices[0][0], "Corrida iniciada para Retail.");
  assert.equal(cron.refreshes, 1);
  assert.doesNotMatch(cron.groupActionsCell(group, false), /Iniciando…/);
});

test("continuar envía el modo en el cuerpo", async () => {
  const calls = [];
  const cron = loadCron(async (url, options) => {
    calls.push([url, options.method, options.body]);
    return { status: 202, ok: true, json: async () => ({ message: "Continuando Retail desde donde quedó." }) };
  });
  const control = {
    dataset: { startGroup: "retail", startMode: "continue" },
    disabled: false,
    textContent: "Continuar",
  };
  await cron.startGroup(control);
  assert.deepEqual(calls, [[
    "/api/admin/cron-batches/retail/start",
    "POST",
    JSON.stringify({ mode: "continue" }),
  ]]);
  assert.equal(cron.notices[0][0], "Continuando Retail desde donde quedó.");
});

test("detener un grupo no pide pausar los demás", async () => {
  const calls = [];
  const cron = loadCron(async (url, options) => {
    calls.push([url, options.method]);
    return { status: 202, ok: true, json: async () => ({ message: "Deteniendo Farmacias. Las demás corridas siguen." }) };
  });
  const button = { dataset: { stopGroup: "farmacias" }, disabled: false, textContent: "Detener" };
  await cron.stopGroup(button);
  assert.deepEqual(calls, [["/api/admin/cron-batches/farmacias/stop", "POST"]]);
  assert.equal(cron.notices[0][0], "Deteniendo Farmacias. Las demás corridas siguen.");
  assert.equal(cron.refreshes, 1);
});

test("scraping de tienda ofrece detener, continuar y reiniciar según estado", () => {
  const cron = loadCron();
  const job = { id: "doite", title: "Doite", status: "running", progress: { phase: "products" }, last_run: { processed: 246 } };
  const running = cron.storeStatusCell(job);
  assert.match(running, /data-stop-store="doite"/);
  assert.match(running, /Detener/);
  assert.doesNotMatch(running, /data-start-store/);

  const stopped = cron.storeStatusCell({
    ...job,
    status: "stopped",
    last_run: { processed: 246 },
  });
  assert.match(stopped, /data-start-mode="continue"/);
  assert.match(stopped, /Continuar/);
  assert.match(stopped, /data-start-mode="restart"/);
  assert.match(stopped, /Reiniciar/);

  const done = cron.storeStatusCell({
    ...job,
    status: "done",
    last_run: { processed: 2296, items: 2296 },
  });
  assert.doesNotMatch(done, /data-start-mode="continue"/);
  assert.match(done, /data-start-mode="restart"/);
  assert.match(done, /Reiniciar/);
  const partialStore = cron.storeStatusCell({
    ...job,
    status: "partial",
    can_continue: true,
    last_run: { processed: 100, items: 500, budget_exhausted: true },
  });
  assert.match(partialStore, /data-start-mode="continue"/);

  const idle = cron.storeStatusCell({ id: "acqui", title: "Acqui", status: "idle" });
  assert.match(idle, /data-start-store="acqui"/);
  assert.match(idle, /Correr scraping/);
  assert.doesNotMatch(idle, /data-start-mode/);

  const failed = cron.storeStatusCell({
    id: "doite",
    title: "Doite",
    status: "failed",
    last_run: { processed: 0 },
  });
  assert.doesNotMatch(failed, /Continuar/);
  assert.match(failed, /Reiniciar/);
});

test("continuar y detener scraping de tienda llaman a las APIs correctas", async () => {
  const calls = [];
  const cron = loadCron(async (url, options) => {
    calls.push([url, options?.method, options?.body]);
    return {
      status: 202,
      ok: true,
      json: async () => ({ message: url.includes("stop") ? "Deteniendo scraping de Doite." : "Continuando scraping de Doite desde donde quedó." }),
    };
  });
  await cron.startStore({
    dataset: { startStore: "doite", startMode: "continue" },
    disabled: false,
    textContent: "Continuar",
  });
  assert.deepEqual(calls[0], [
    "/api/admin/store-scrape",
    "POST",
    JSON.stringify({ tienda: "doite", mode: "continue" }),
  ]);
  await cron.stopStore({
    dataset: { stopStore: "doite" },
    disabled: false,
    textContent: "Detener",
  });
  assert.deepEqual(calls[1], ["/api/admin/store-scrape/doite/stop", "POST", undefined]);
});

test("la tienda seleccionada sin corrida previa aparece en la tabla", () => {
  const tbody = { innerHTML: "" };
  const wrap = { hidden: true, querySelector: (sel) => (sel === "tbody" ? tbody : null) };
  const select = { value: "falabella" };
  const nodes = {
    "store-jobs-wrap": wrap,
    "store-scrape-meta": { textContent: "" },
    "store-select": select,
  };
  const cron = loadCron();
  cron.$ = (id) => nodes[id] || null;
  const payload = {
    store_jobs: [
      { id: "decathlon", title: "decathlon", status: "done", last_run: { processed: 1, items: 1 } },
    ],
    stores: [
      { id: "falabella", title: "Falabella Chile", group: "retail", group_title: "Retail" },
      { id: "decathlon", title: "decathlon", group: "deporte", group_title: "Deporte" },
    ],
  };
  cron.renderStoreJobs(payload);
  assert.equal(wrap.hidden, false);
  assert.match(tbody.innerHTML, /data-tienda="falabella"/);
  assert.match(tbody.innerHTML, /Falabella/);
  assert.doesNotMatch(tbody.innerHTML, /Falabella Chile/);
  assert.match(tbody.innerHTML, /data-start-store="falabella"/);
  assert.match(tbody.innerHTML, /Correr scraping/);
  assert.match(tbody.innerHTML, /cron-store-selected/);
});

test("syncRunButton habilita Correr scraping para tienda idle sin job en Mongo", () => {
  const select = { value: "falabella" };
  const button = { dataset: {}, disabled: true, textContent: "Correr scraping" };
  const cron = loadCron();
  cron.$ = (id) => ({ "store-select": select, "store-run": button, "store-scrape-actions": { innerHTML: "" } }[id] || null);
  cron.lastStoreJobs = [];
  cron.syncRunButton();
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Correr scraping");
  assert.equal(button.dataset.startStore, "falabella");
  assert.equal(button.dataset.startMode, "");
});

test("el formulario de tienda pasa a Continuar, Reiniciar o Detener según el estado", () => {
  const select = { value: "doite" };
  const button = { dataset: {}, disabled: true, textContent: "Correr scraping" };
  const actions = { innerHTML: "" };
  const nodes = {
    "store-select": select,
    "store-run": button,
    "store-scrape-actions": actions,
  };
  const cron = loadCron();
  cron.$ = (id) => nodes[id] || null;
  const vm = require("node:vm");
  vm.runInContext(
    `lastStoreJobs = ${JSON.stringify([
      { id: "doite", title: "Doite", status: "failed", last_run: { processed: 246, items: 2324 } },
    ])}`,
    cron,
  );

  cron.syncRunButton();
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Continuar");
  assert.equal(button.dataset.startMode, "continue");
  assert.equal(button.dataset.startStore, "doite");
  assert.match(actions.innerHTML, /data-start-mode="restart"/);
  assert.match(actions.innerHTML, /Reiniciar/);

  vm.runInContext(`lastStoreJobs[0].status = "partial"`, cron);
  cron.syncRunButton();
  assert.equal(button.textContent, "Continuar");
  assert.equal(button.dataset.startMode, "continue");

  vm.runInContext(
    `lastStoreJobs[0] = ${JSON.stringify({
      id: "doite",
      title: "Doite",
      status: "done",
      last_run: { processed: 2324, items: 2324 },
    })}`,
    cron,
  );
  cron.syncRunButton();
  assert.equal(button.textContent, "Reiniciar");
  assert.equal(button.dataset.startMode, "restart");
  assert.equal(actions.innerHTML, "");

  vm.runInContext(
    `lastStoreJobs[0] = ${JSON.stringify({
      id: "doite",
      title: "Doite",
      status: "running",
      progress: { phase: "products" },
      last_run: { processed: 10 },
    })}`,
    cron,
  );
  cron.syncRunButton();
  assert.equal(button.disabled, true);
  assert.equal(button.textContent, "En curso");
  assert.match(actions.innerHTML, /data-stop-store="doite"/);
  assert.match(actions.innerHTML, /Detener/);
});

test("scraping básico ofrece detener, continuar y reiniciar según estado", () => {
  const cron = loadCron();
  const job = {
    id: "scraping_basico",
    title: "Scraping básico",
    status: "running",
    progress: { phase: "products", processed: 96, items: 202001 },
    last_run: { processed: 96 },
  };
  const running = cron.basicStatusCell(job);
  assert.match(running, /data-stop-basic/);
  assert.match(running, /Detener/);
  assert.doesNotMatch(running, /data-basic-mode/);

  const stopping = cron.basicStatusCell({
    ...job,
    progress: { ...job.progress, phase: "stopping" },
  });
  assert.match(stopping, /Deteniendo/);
  assert.match(stopping, / disabled/);

  const stopped = cron.basicStatusCell({
    ...job,
    status: "stopped",
    last_run: { processed: 96, items: 202001 },
  });
  assert.match(stopped, /data-basic-mode="continue"/);
  assert.match(stopped, /Continuar/);
  assert.match(stopped, /data-basic-mode="restart"/);
  assert.match(stopped, /Reiniciar/);

  const done = cron.basicStatusCell({
    ...job,
    status: "done",
    last_run: { processed: 202001, items: 202001 },
  });
  assert.doesNotMatch(done, /data-basic-mode="continue"/);
  assert.match(done, /data-basic-mode="restart"/);
});

test("detener scraping básico llama a la API de stop", async () => {
  const calls = [];
  const cron = loadCron(async (url, options) => {
    calls.push([url, options?.method]);
    return { status: 202, ok: true, json: async () => ({ message: "Deteniendo scraping básico." }) };
  });
  await cron.stopBasicScrape({ dataset: { stopBasic: "1" }, disabled: false, textContent: "Detener" });
  assert.deepEqual(calls, [["/api/admin/basic-scrape/stop", "POST"]]);
  assert.equal(cron.notices[0][0], "Deteniendo scraping básico.");
  assert.equal(cron.refreshes, 1);
});

test("un rechazo se muestra y permite reintentar tras actualizar", async () => {
  let attempts = 0;
  const cron = loadCron(async () => {
    attempts += 1;
    return { status: 409, ok: false, json: async () => ({ detail: "Ya hay una corrida en curso." }) };
  });
  const control = button();
  await cron.startGroup(control);
  assert.equal(cron.notices[0][0], "Ya hay una corrida en curso.");
  assert.equal(cron.notices[0][1], false);
  assert.equal(cron.refreshes, 1);
  assert.equal(control.disabled, false);
  await cron.startGroup(control);
  assert.equal(attempts, 2);
});
