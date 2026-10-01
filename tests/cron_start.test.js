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
  const idle = cron.groupStatusCell(group, false);
  assert.match(idle, /Iniciar ahora/);
  assert.match(idle, /data-start-group="retail"/);
  assert.doesNotMatch(idle, / disabled/);
  for (const status of ["done", "failed", "stopped"]) {
    assert.doesNotMatch(cron.groupStatusCell({ ...group, status }, false), /data-start-group/);
    assert.doesNotMatch(cron.groupStatusCell({ ...group, status }, false), /data-stop-group/);
  }
  for (const status of ["running", "paused"]) {
    const cell = cron.groupStatusCell({ ...group, status, progress: { phase: "products" } }, false);
    assert.match(cell, /data-stop-group="retail"/);
    assert.match(cell, /Detener/);
    assert.doesNotMatch(cell, /data-start-group/);
  }
  const stopping = cron.groupStatusCell({ ...group, status: "running", progress: { phase: "stopping" } }, false);
  assert.match(stopping, /Deteniendo/);
  assert.match(stopping, / disabled/);
  assert.doesNotMatch(cron.groupStatusCell({ ...group, store_count: 0 }, false), /data-start-group/);
  assert.match(cron.groupStatusCell(group, true), / disabled/);
  assert.match(cron.groupStatusCell(group, true), /Reanuda las corridas/);
});

test("doble clic y redibujado no duplican la solicitud", async () => {
  let resolve;
  const pending = new Promise((done) => { resolve = done; });
  const calls = [];
  const cron = loadCron((url, options) => { calls.push([url, options.method]); return pending; });
  const firstButton = button();
  const first = cron.startGroup(firstButton);
  assert.equal(firstButton.disabled, true);
  assert.equal(firstButton.textContent, "Iniciando…");
  assert.match(cron.groupStatusCell(group, false), / disabled/);
  await cron.startGroup(button());
  assert.deepEqual(calls, [["/api/admin/cron-batches/retail/start", "POST"]]);
  resolve({ status: 202, ok: true, json: async () => ({ message: "Corrida iniciada para Retail." }) });
  await first;
  assert.equal(cron.notices[0][0], "Corrida iniciada para Retail.");
  assert.equal(cron.refreshes, 1);
  assert.doesNotMatch(cron.groupStatusCell(group, false), /Iniciando…/);
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
