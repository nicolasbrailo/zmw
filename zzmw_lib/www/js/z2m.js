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

// The single page visibility listener: everything that cares about the page being hidden or visible (mPoll,
// apps' on_app_became_visible) registers here. cb(isVisible) runs on every change; returns a handle with stop().
const mVisibilityCbs = new Set();

function mOnVisibilityChange(cb) {
  const handle = { cb, stop: () => mVisibilityCbs.delete(handle) };
  mVisibilityCbs.add(handle);
  return handle;
}

document.addEventListener('visibilitychange', () => {
  const isVisible = !document.hidden;
  // Iterate a copy: callbacks may (un)register others, eg by mounting or unmounting components
  for (const handle of [...mVisibilityCbs]) {
    handle.cb(isVisible);
  }
});

// Periodic polling that pauses while the page is hidden. Background tabs get throttled, then frozen, and
// their in-flight requests aborted; polling there is wasted work at best, and spurious errors at worst. On
// becoming visible, a poller picks up where it left off: it runs immediately only if a full interval went by
// since its last run, so quickly switching tabs back and forth doesn't trigger a burst of requests.
// Callers are expected to fetch once themselves on mount; the first poll runs one interval after mPoll().
function mPoll(fn, intervalMs) {
  const poller = { timer: null };
  let lastRunAt = Date.now();
  const schedule = (delayMs) => {
    poller.timer = setTimeout(() => {
      lastRunAt = Date.now();
      fn();
      schedule(intervalMs);
    }, delayMs);
  };

  const visibility = mOnVisibilityChange((isVisible) => {
    clearTimeout(poller.timer);
    poller.timer = null;
    if (isVisible) {
      schedule(Math.max(0, intervalMs - (Date.now() - lastRunAt)));
    }
  });
  poller.stop = () => {
    visibility.stop();
    clearTimeout(poller.timer);
    poller.timer = null;
  };
  if (!document.hidden) {
    schedule(intervalMs);
  }
  return poller;
}

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
  // The probe is an mPoll, so it pauses while hidden and resumes (within its 3s interval) once visible again
  mNet._probe = mPoll(_mNetProbeMaybeShowBanner, 3000);
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

// Check if the server is reachable, and update mNet's state either way. Useful when something other than an HTTP
// request fails and can't tell why (eg a websocket closing). Any HTTP response, even an error one, means the
// server is reachable. Times out before the next probe is due, so probes to an unresponsive host don't pile up
// waiting for a TCP timeout.
function mNetProbe() {
  return mFetch(window.location.href, { method: 'HEAD', cache: 'no-store', signal: AbortSignal.timeout(2500) });
}

// While the net is down: mNetProbe, and show the banner if it's still down. Needed when the net went down in the
// background, since mNetMarkDown doesn't show the banner while hidden.
function _mNetProbeMaybeShowBanner() {
  mNetProbe().catch(() => { if (mNet.down) _mNetShowBanner(); });
}

window.addEventListener('online', () => {
  if (mNet.down) _mNetProbeMaybeShowBanner();
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

// Hosts a zmw app (a class component with a static buildProps), and calls its on_app_became_visible (if it has
// one) when the page becomes visible, for as long as it's mounted. Don't use directly: see z2mEmbedApp.
class ZmwAppHost extends React.Component {
  constructor(props) {
    super(props);
    this.appRef = React.createRef();
  }

  componentDidMount() {
    this._visibility = mOnVisibilityChange((isVisible) => {
      const app = this.appRef.current;
      if (isVisible && app?.on_app_became_visible) {
        console.log(`${this.props.app.name} became visible, will refresh state`);
        app.on_app_became_visible();
      }
    });
  }

  componentWillUnmount() {
    this._visibility.stop();
  }

  render() {
    return React.createElement(this.props.app, { ...this.props.appProps, ref: this.appRef });
  }
}

// Render a zmw app inside another one (eg the dashboard). Use this instead of a bare React.createElement(app, ...),
// or the embedded app's on_app_became_visible will never run.
function z2mEmbedApp(appClass, appProps) {
  return React.createElement(ZmwAppHost, { key: appProps.key, app: appClass, appProps });
}

function z2mStartReactApp(appRootSelector, appClass, apiBasePath='') {
  ReactDOM.createRoot(document.querySelector(appRootSelector)).render(
    z2mEmbedApp(appClass, appClass.buildProps(apiBasePath))
  );

  // appLoaded
  m$('global_loading').classList.add('app-finished-loading');
  m$('global_loading').classList.remove('app-loading');
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
