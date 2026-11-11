/* auth.js —— token 存取、带鉴权的 fetch、WebSocket 订阅、页面守卫 */
(function () {
  const TOKEN_KEY = 'dispatcher.token';

  window.Auth = {
    get token() { return localStorage.getItem(TOKEN_KEY) || ''; },
    get user() {
      try { return JSON.parse(localStorage.getItem('dispatcher.user') || 'null'); }
      catch (e) { return null; }
    },
    save(token, user) {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem('dispatcher.user', JSON.stringify(user));
    },
    clear() {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem('dispatcher.user');
    },

    /* 带 X-Token 的 fetch；401 时跳登录页（乘客端 exclude401） */
    async api(url, opts = {}, exclude401 = false) {
      const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
      if (Auth.token) headers['X-Token'] = Auth.token;
      const res = await fetch(url, Object.assign({}, opts, { headers }));
      if (res.status === 401 && !exclude401) {
        Auth.clear();
        location.href = '/login?next=' + encodeURIComponent(location.pathname);
        throw new Error('未登录');
      }
      if (!res.ok) {
        let msg = res.status + ' ' + res.statusText;
        try { const j = await res.json(); msg = j.detail || msg; } catch (e) { }
        throw new Error(msg);
      }
      const ct = res.headers.get('content-type') || '';
      return ct.includes('json') ? res.json() : res.text();
    },

    /* 页面守卫：需要登录的角色 */
    guard(roles) {
      const u = Auth.user;
      if (!Auth.token || !u || !roles.includes(u.role)) {
        location.href = '/login?next=' + encodeURIComponent(location.pathname);
        return false;
      }
      return true;
    },

    logout() { Auth.clear(); location.href = '/login'; },
  };

  /* Live —— WebSocket 实时状态，断线自动降级轮询 */
  window.Live = {
    start(onState, fallbackPollMs) {
      let ws = null, timer = null, alive = false;
      const poll = async () => {
        try {
          const st = await (await fetch('/api/state')).json();
          onState(st, 'poll');
        } catch (e) { /* 网络抖动忽略 */ }
      };
      const connect = () => {
        try {
          const proto = location.protocol === 'https:' ? 'wss' : 'ws';
          ws = new WebSocket(`${proto}://${location.host}/ws`);
        } catch (e) { return; }
        ws.onopen = () => {
          alive = true;
          if (timer) { clearInterval(timer); timer = null; }
          ws.send('hello');
        };
        ws.onmessage = ev => {
          try { onState(JSON.parse(ev.data), 'ws'); } catch (e) { }
        };
        ws.onclose = () => {
          alive = false;
          if (!timer && fallbackPollMs) timer = setInterval(poll, fallbackPollMs);
          setTimeout(connect, 3000);   // 3s 后重连
        };
        ws.onerror = () => { try { ws.close(); } catch (e) { } };
      };
      connect();
      return { get alive() { return alive; } };
    },
  };

  window.fmtAgo = function (iso) {
    if (!iso) return '';
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    return s < 60 ? Math.round(s) + ' 秒前' : Math.round(s / 60) + ' 分钟前';
  };
})();
