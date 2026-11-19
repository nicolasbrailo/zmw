function m$(elem) {
  return document.getElementById(elem);
}

// Drop-in fetch() replacement that keeps mNet's state up to date: use it for any request that can't go through
// mAjax (eg POST or FormData bodies). Rejects with fetch's own error, tagged with `netDown` so that
// showGlobalError ignores it (mNet reports it instead).
function mFetch(...args) {
  return fetch(...args).then(
    (response) => {
      mNetMarkUp();
      return response;
    },
    (err) => {
      mNetMarkDown();
      err.netDown = true;
      throw err;
    });
}

function mAjax(cfg) {
  const method = (cfg.type || 'GET').toUpperCase();
  const isJson = cfg.dataType?.toLowerCase() === 'json';

  // Cache busting for GET/HEAD (only when explicitly requested)
  let url = cfg.url;
  if (cfg.cache === true && (method === 'GET' || method === 'HEAD')) {
    const t = Date.now();
    url = (url.indexOf('?') === -1) ? `${url}?_=${t}` : `${url}&_=${t}`;
  }

  // Build fetch options
  const options = { method };

  if (method === 'PUT' && cfg.data != null) {
    if (isJson) {
      if (typeof cfg.data !== 'object') {
        const err = `mAjax: dataType for '${cfg.url}' is JSON but data is not an object/array: ${typeof cfg.data}`;
        console.error(err, cfg);
        cfg.error?.({
          status: 0,
          statusText: `Invalid JSON data for ${cfg.url}`,
          responseText: err,
        });
        return;
      }
      options.headers = { 'Content-Type': 'application/json' };
      options.body = JSON.stringify(cfg.data);
    } else {
      options.headers = { 'Content-Type': 'application/x-www-form-urlencoded' };
      options.body = cfg.data;
    }
  } else if (cfg.data) {
    console.error("Request.data is not null for non-PUT method, not sure if valid", cfg);
  }

  // A rejected fetch means the server wasn't reachable at all (vs an HTTP error, which still is a response)
  mFetch(url, options)
    .then(async (response) => {
      if (!response.ok) {
        throw {
          status: response.status,
          statusText: response.statusText,
          responseText: await response.text(),
          responseURL: response.url,
        };
      }
      const text = await response.text();
      if (isJson) {
        return text.trim().length === 0 ? {} : JSON.parse(text);
      }
      return text;
    })
    .then(cfg.success)
    .catch((err) => {
      if (err?.netDown) {
        console.warn(`mAjax: can't reach server for ${url}`, err);
        // Callers still get an error (eg to reset their UI), but showGlobalError ignores it: mNet owns that banner
        cfg.error?.({
          netDown: true,
          status: 0,
          statusText: "Net down",
          responseText: "Server unreachable or connection aborted",
        });
      } else {
        cfg.error?.(err);
      }
    });
}

// Periodic polling that pauses while the page is hidden. Background tabs get throttled, then frozen, and
// their in-flight requests aborted; polling there is wasted work at best, and spurious errors at worst. On
// becoming visible, every poller runs once immediately and then resumes its interval.
const mPollers = new Set();

function mPoll(fn, intervalMs) {
  const poller = { fn, intervalMs, timer: null };
  poller.stop = () => {
    clearInterval(poller.timer);
    poller.timer = null;
    mPollers.delete(poller);
  };
  mPollers.add(poller);
  if (!document.hidden) {
    poller.timer = setInterval(fn, intervalMs);
  }
  return poller;
}

document.addEventListener('visibilitychange', () => {
  for (const poller of mPollers) {
    clearInterval(poller.timer);
    poller.timer = null;
    if (!document.hidden) {
      poller.fn();
      poller.timer = setInterval(poller.fn, poller.intervalMs);
    }
  }
});

// Global "can't reach server" state. Any mAjax that fails at the network level marks the net as down, which
// shows a "Net down" banner and starts probing the server; any response (from a probe or any other request)
// marks it as up again, and dismisses the banner if it's still showing.
const mNet = {
  down: false,
  _probe: null,
  _bannerShown: false,   // Show the banner once per outage, so acking it sticks
  _bannerVisible: false, // False once acked or replaced by a real error, so we don't dismiss someone else's error
};

function mNetMarkDown() {
  if (mNet.down) return;
  mNet.down = true;
  mNet._bannerShown = false;
  // The probe is an mPoll, so it pauses while hidden and runs as soon as the page is visible again
  mNet._probe = mPoll(_mNetProbe, 3000);
  // If this happened in the background (eg a request aborted by the browser when freezing the tab), wait for a
  // probe to fail before complaining: the network is likely to be fine by the time the user looks again.
  if (!document.hidden) {
    _mNetShowBanner();
  }
}

function mNetMarkUp() {
  if (!mNet.down) return;
  console.log("mNet: server reachable again");
  mNet.down = false;
  mNet._probe.stop();
  mNet._probe = null;
  if (mNet._bannerVisible) {
    dismissGlobalError();
  }
}

function _mNetShowBanner() {
  if (mNet._bannerShown) return;
  mNet._bannerShown = true;
  m$('global_error_msg').innerText = "Net down \n\n Can't reach server, will dismiss once it's back";
  m$('global_error_ui').classList.remove('no-error');
  mNet._bannerVisible = true;
}

function _mNetProbe() {
  // Any HTTP response, even an error one, means the server is reachable. Time out before the next probe is due,
  // so probes to an unresponsive host don't pile up waiting for a TCP timeout.
  fetch(window.location.href, { method: 'HEAD', cache: 'no-store', signal: AbortSignal.timeout(2500) })
    .then(mNetMarkUp, () => { if (mNet.down) _mNetShowBanner(); });
}

window.addEventListener('online', () => {
  if (mNet.down) _mNetProbe();
});

function mTextGet(url, success_cb, error_cb) {
  mAjax({
    url,
    cache: true,
    type: 'GET',
    dataType: 'text',
    success: success_cb,
    error: error_cb || showGlobalError,
  });
}

function mJsonGet(url, success_cb, error_cb) {
  mAjax({
    url,
    type: 'GET',
    dataType: 'JSON',
    success: success_cb,
    error: error_cb ? (e) => { error_cb(e); showGlobalError(e); } : showGlobalError,
  });
}

function mJsonPut(url, val, success_cb, error_cb) {
  mAjax({
    url,
    type: 'PUT',
    dataType: 'JSON',
    data: val,
    success: success_cb || (() => {}),
    error: error_cb ? (e) => { error_cb(e); showGlobalError(e); } : showGlobalError,
  });
}

function z2mStartReactApp(appRootSelector, appClass, apiBasePath='') {
  const appRef = React.createRef();
  ReactDOM.createRoot(document.querySelector(appRootSelector)).render(
    React.createElement(appClass, { ...appClass.buildProps(apiBasePath), ref: appRef })
  );

  // appLoaded
  m$('global_loading').classList.add('app-finished-loading');
  m$('global_loading').classList.remove('app-loading');

  if (appClass.prototype.on_app_became_visible) {
    const app_visibility = new VisibilityCallback();
    app_visibility.app_became_visible = () => {
      console.log("App became visible, will refresh state")
      appRef.current.on_app_became_visible();
    }
  }
}

const showGlobalError = (msg) => {
  // Network errors are reported (and dismissed) by mNet
  if (msg?.netDown) return;
  mNet._bannerVisible = false;
  if (typeof(msg) == "string") {
    m$('global_error_msg').innerText = msg;
  } else if (typeof(msg) == "object" && msg.responseText || msg.status || msg.statusText) {
    // Probably an ajax response object
    const stat = `Error ${msg.status||'???'}: ${msg.statusText||'unknown'}`;
    m$('global_error_msg').innerText = `${stat} \n\n ${msg.responseText||''}`;
  } else {
    m$('global_error_msg').innerText = msg;
  }
  m$('global_error_ui').classList.remove('no-error');
};

const dismissGlobalError = () => {
  mNet._bannerVisible = false;
  m$('global_error_msg').innerText = '';
  m$('global_error_ui').classList.add('no-error');
};

if (m$('global_error_ui_ack')) {
  m$('global_error_ui_ack').onclick = dismissGlobalError;
}
