(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PriceHistory = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function addDays(day, count) {
    const [year, month, date] = String(day).split("-").map(Number);
    return new Date(Date.UTC(year, month - 1, date + count)).toISOString().slice(0, 10);
  }

  function validPrice(value) {
    if (value == null || value === "") return null;
    const price = Number(value);
    return Number.isFinite(price) && price > 0 ? price : null;
  }

  function filter(observations, days, today) {
    const start = days ? addDays(today, -(days - 1)) : "0000-00-00";
    const byDay = new Map();
    for (const raw of observations || []) {
      const day = raw && raw.day;
      if (!day || day < start || day > today) continue;
      const offer = validPrice(raw.offer);
      const normal = validPrice(raw.normal);
      if (offer == null && normal == null) continue;
      byDay.set(day, { day, offer, normal });
    }
    return [...byDay.values()].sort((left, right) => left.day.localeCompare(right.day));
  }

  function stats(values) {
    const valid = (values || []).map(validPrice).filter((value) => value != null);
    if (!valid.length) return null;
    return {
      current: valid[valid.length - 1],
      min: Math.min(...valid),
      max: Math.max(...valid),
      average: Math.round(valid.reduce((total, value) => total + value, 0) / valid.length),
      first: valid[0],
      count: valid.length,
    };
  }

  function hasMeaningfulNormal(observations) {
    return (observations || []).some(
      (point) => validPrice(point.offer) != null
        && validPrice(point.normal) != null
        && validPrice(point.offer) !== validPrice(point.normal)
    );
  }

  return { addDays, filter, stats, hasMeaningfulNormal };
});
