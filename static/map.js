/* 地图渲染：高德 JS API v2.0（有 key）/ 自绘 SVG 示意图（无 key 兜底）。
   renderMap(el, state) → 'amap' | 'schematic'
   state.map = { provider, js_key, security_code } */
(function () {
  const PAD = 34, W = 760, H = 440;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>\"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  /* ------------------------------------------------- 示意图（兜底） */
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

  function drawSchematic(el, state) {
    const allStops = state.routes.flatMap(r => r.stops || []);
    if (!allStops.length) { el.innerHTML = '<div class="empty" style="padding:20px">暂无线路数据</div>'; return; }
    const proj = project(allStops);
    const parts = [`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">`];
    parts.push(`<rect x="0" y="0" width="${W}" height="${H}" fill="#141b29"/>`);
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

  /* ------------------------------------------------- 高德地图 */
  let amapReady = null;
  function loadAMap(key, securityCode) {
    if (amapReady) return amapReady;
    amapReady = new Promise((resolve, reject) => {
      if (securityCode) window._AMapSecurityConfig = { securityJsCode: securityCode };
      const s = document.createElement('script');
      s.src = 'https://webapi.amap.com/maps?v=2.0&key=' + encodeURIComponent(key);
      s.onload = () => resolve(window.AMap);
      s.onerror = () => { amapReady = null; reject(new Error('AMap load failed')); };
      document.head.appendChild(s);
    });
    return amapReady;
  }

  async function drawAMap(el, state) {
    const AMap = await loadAMap(state.map.js_key, state.map.security_code);
    const all = state.routes.flatMap(r => r.stops || []);
    if (!all.length && !(state.vehicles || []).some(v => v.lat != null)) {
      el.innerHTML = '<div class="empty" style="padding:20px">暂无线路数据</div>';
      return;
    }
    if (el._amap) {                       // 已初始化：只增量更新，避免闪烁
      updateOverlays(el, AMap, state);
      return;
    }
    el.innerHTML = '';
    const center = all.length ? [all[0].lng, all[0].lat] : [113.93, 22.54];
    const map = new AMap.Map(el, { center, zoom: 15, viewMode: '2D', mapStyle: 'amap://styles/dark' });
    el._amap = map;
    el._overlays = [];
    updateOverlays(el, AMap, state);
    if (all.length > 1) map.setFitView(null, true, [40, 40, 40, 40]);
  }

  function clearOverlays(el) {
    (el._overlays || []).forEach(o => el._amap.remove(o));
    el._overlays = [];
  }

  function updateOverlays(el, AMap, state) {
    clearOverlays(el);
    const ov = [];
    state.routes.forEach(route => {
      const stops = route.stops || [];
      if (stops.length >= 2) {
        const path = stops.map(s => [s.lng, s.lat]);
        if (route.direction === 'loop') path.push(path[0]);
        ov.push(new AMap.Polyline({
          path, strokeColor: route.color, strokeWeight: 5, strokeOpacity: 0.8,
          lineJoin: 'round', zIndex: 10,
        }));
      }
      stops.forEach(s => {
        ov.push(new AMap.Marker({
          position: [s.lng, s.lat], anchor: 'center', zIndex: 20,
          content: `<div style="color:#cfe0ff;font-size:11px;background:#0f1420cc;padding:1px 6px;border-radius:6px;border:1px solid ${route.color};white-space:nowrap">${esc(s.name)}</div>`,
        }));
      });
    });
    (state.vehicles || []).forEach(v => {
      if (v.lat == null || v.lng == null) return;
      const eta = v.eta_min != null ? ` · ETA ${v.eta_min}min` : '';
      ov.push(new AMap.Marker({
        position: [v.lng, v.lat], anchor: 'center', zIndex: 40,
        content: `<div style="background:${esc(v.color || '#2f6fed')};color:#fff;font-size:12px;padding:3px 8px;border-radius:6px;white-space:nowrap;border:1px solid #fff3">${esc(v.plate)} · ${esc(v.stop_name || '未发车')}${eta}</div>`,
      }));
    });
    ov.forEach(o => el._amap.add(o));
    el._overlays = ov;
  }

  window.renderMap = async function (el, state) {
    const mp = state.map || {};
    if (mp.provider === 'amap' && mp.js_key) {
      try {
        await drawAMap(el, state);
        return 'amap';
      } catch (e) {
        console.warn('高德地图加载失败，回退示意图', e);
      }
    }
    drawSchematic(el, state);
    return 'schematic';
  };
})();
