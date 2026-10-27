export function ago(then, now) {
  const minutes = Math.max(0, Math.floor((now - then) / 60000));
  const [n, unit] = minutes < 60 ? [minutes, "minute"] : minutes < 48 * 60 ? [Math.floor(minutes / 60), "hour"] : [Math.floor(minutes / 1440), "day"];
  return `${n} ${unit}${n === 1 ? "" : "s"} ago`;
}
