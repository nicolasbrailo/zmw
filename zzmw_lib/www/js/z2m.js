function m$(elem) {
  return document.getElementById(elem);
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

  fetch(url, options)
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
      // Network error (fetch rejected) vs HTTP error (we threw above)
      if (err instanceof TypeError) {
        cfg.error?.({
          status: 0,
          statusText: "Can't reach server",
          responseText: "Server unreachable or connection aborted",
        });
      } else {
        cfg.error?.(err);
      }
    });
}

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

if (m$('global_error_ui_ack')) {
  m$('global_error_ui_ack').onclick = () => {
    m$('global_error_msg').innerText = '';
    m$('global_error_ui').classList.add('no-error');
  };
}
