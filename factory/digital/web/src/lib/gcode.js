// G 代码解析成刀位点 [x, y, z, 是否快移]，规则与 freecad/wq_cam_keyway.py 的 parse() 相同；
// 第 13 轮：G00 / G01 是模态的（数控编程的程序后面几行只写坐标），也认 X35.0 这种带小数点的写法
export function parseGcode(text) {
  const pos = { X: 0, Y: 0, Z: 0 };
  const pts = [];
  let mode = null;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/\([^)]*\)/g, ' ').split(';')[0].trim().toUpperCase();
    if (!line || line === '%' || line[0] === 'O') continue;
    const words = line.match(/[A-Z][-+]?[0-9.]+/g) || [];
    for (const w of words) {
      if (w[0] !== 'G') continue;
      const g = parseFloat(w.slice(1));
      if (g === 0 || g === 1) mode = g;
      else if ([28, 80, 81, 83, 43, 54].includes(g)) mode = g === 28 ? null : mode;
    }
    if (mode === null || !words.some((w) => w[0] in pos)) continue;
    if (words.some((w) => w === 'G28' || w === 'G43' || w.startsWith('G8'))) continue;
    for (const w of words) if (w[0] in pos) pos[w[0]] = parseFloat(w.slice(1));
    pts.push([pos.X, pos.Y, pos.Z, mode === 0]);
  }
  return pts;
}
