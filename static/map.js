/* 地图渲染：有腾讯地图 key 用真实地图，没有则用自绘示意图（DEMO 默认）。 */
(function () {
  const PAD = 34, W = 760, H = 440;

  function project(stops) {
    const lats = stops.map(s => s.lat), lngs = stops.map(s => s.lng);
    const minLat = Math.min(...lats), maxLat = Math.max(...lats);
    const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
    const spanLat = Math.max(maxLat - minLat, 1e-4), spanLng = Math.max(maxLng - minLng, 1e-4);
    return (lat, lng) => [
      PAD + (lng - minLng) / spanLng * (W - 2 * PAD),
      H - PAD - (lat - minLat) / spanLat * (H - 2 * PAD),
    ];
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function drawSchematic(el, state) {
    const allStops = state.routes.flatMap(r => r.stops || []);
    if (!allStops.length) { el.innerHTML = '<div class="empty" style="padding:20px">暂无线路数据</div>'; return; }
    const proj = project(allStops);
    const parts = [`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">`];
    parts.push(`<rect x="0" y="0" width="${W}" height="${H}" fill="#141b29"/>`);
    // 网格
    for (let x = 40; x < W; x += 60) parts.push(`<line x1="${x}" y1="0" x2="${x}" y2="${H}" stroke="#1b2436"/>`);
    for (let y = 40; y < H; y += 60) parts.push(`<line x1="0" y1="${y}" x2="${W}" y2="${y}" stroke="#1b2436"/>`);

    state.routes.forEach(route => {
      const stops = route.stops || [];
      if (!stops.length) return;
      const pts = stops.map(s => proj(s.lat, s.lng));
      const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ') + (route.direction === 'loop' ? ' Z' : '');
      parts.push(`<path d="${d}" fill="none" stroke="${esc(route.color)}" stroke-width="4" stroke-opacity=".55" stroke-linejoin="round"/>`);
      pts.forEach((p, i) => {
        parts.push(`<circle cx="${p[0]}" cy="${p[1]}" r="7" fill="#0f1420" stroke="${esc(route.color)}" stroke-width="3"/>`);
        const ly = p[1] + (i % 2 ? 20 : -14);
        parts.push(`<text x="${p[0]}" y="${ly}" fill="#9fb0cc" font-size="12" text-anchor="middle">${esc(stops[i].name)}</text>`);
      });
      parts.push(`<text x="${pts[0][0] + 12}" y="${pts[0][1] - 22}" fill="${esc(route.color)}" font-size="12" font-weight="600">${esc(route.name)}</text>`);
    });

    (state.vehicles || []).forEach((v, idx) => {
      if (v.lat == null || v.lng == null) return;
      const [x, y] = proj(v.lat, v.lng);
      const dx = (idx % 3 - 1) * 26, dy = -22 - Math.floor(idx / 3) * 20;
      const fresh = v.arrived_at ? '●' : '○';
      parts.push(`<g transform="translate(${x + dx},${y + dy})">
        <rect x="-30" y="-11" width="60" height="21" rx="6" fill="${esc(v.color || '#2f6fed')}" fill-opacity=".9"/>
        <text x="0" y="4" fill="#fff" font-size="11" text-anchor="middle">${esc((v.plate || '').replace('粤B·', ''))}</text>
        <text x="0" y="24" fill="#8b9ab5" font-size="10" text-anchor="middle">${fresh} ${esc(v.arrived_at ? (v.stop_name || '已到站') : '未发车')}</text>
      </g>`);
    });
    parts.push('</svg>');
    el.innerHTML = parts.join('');
  }

  let mapReady = null;
  function loadTencent(key) {
    if (mapReady) return mapReady;
    mapReady = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = `https://map.qq.com/api/gljs?v=1.exp&key=${encodeURIComponent(key)}`;
      s.onload = () => resolve(window.TMap);
      s.onerror = reject;
      document.head.appendChild(s);
    });
    return mapReady;
  }

  async function drawTencent(el, state) {
    const TMap = await loadTencent(state.map_key);
    const all = state.routes.flatMap(r => r.stops || []);
    if (!all.length) return;
    const vehGeoms = (state.vehicles || []).filter(v => v.lat != null).map(v => ({
      id: 'v' + v.id,
      position: new TMap.LatLng(v.lat, v.lng),
      content: `<div style="background:${v.color || '#2f6fed'};color:#fff;font-size:12px;padding:3px 8px;border-radius:6px;white-space:nowrap">${esc(v.plate)} · ${esc(v.stop_name || '未发车')}</div>`,
    }));
    if (el._tmap && el._vehLayer) {          // 已初始化：只更新车辆位置，避免重建地图闪烁
      el._vehLayer.setGeometries(vehGeoms);
      return;
    }
    const center = new TMap.LatLng(all[0].lat, all[0].lng);
    if (el._tmap) { el._tmap.destroy(); }
    const map = new TMap.Map(el, { center, zoom: 15, viewMode: '2D' });
    el._tmap = map;
    state.routes.forEach(route => {
      const paths = (route.stops || []).map(s => new TMap.LatLng(s.lat, s.lng));
      if (paths.length < 2) return;
      if (route.direction === 'loop') paths.push(paths[0]);
      new TMap.MultiPolyline({
        map,
        styles: { line: new TMap.PolylineStyle({ color: route.color, width: 5, borderWidth: 1, borderColor: '#ffffff' }) },
        geometries: [{ styleId: 'line', paths }],
      });
    });
    new TMap.MultiMarker({
      map,
      geometries: all.map((s, i) => ({ id: 'stop' + i, position: new TMap.LatLng(s.lat, s.lng), content: `<div style="color:#cfe0ff;font-size:12px;background:#0f1420cc;padding:2px 6px;border-radius:6px">${esc(s.name)}</div>` })),
    });
    el._vehLayer = new TMap.MultiMarker({ map, geometries: vehGeoms });
  }

  window.renderMap = async function (el, state) {
    if (state.map_key) {
      try {
        if (el._tmap) { el._tmap.destroy(); el._tmap = null; }
        el.innerHTML = '';
        await drawTencent(el, state);
        return 'tencent';
      } catch (e) {
        console.warn('腾讯地图加载失败，回退示意图', e);
      }
    }
    drawSchematic(el, state);
    return 'schematic';
  };
})();
