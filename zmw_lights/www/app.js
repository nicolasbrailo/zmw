function filterMeta(meta) {
  const filtered = {
    description: meta.description,
    model: meta.model,
    name: meta.name,
    real_name: meta.real_name,
    thing_type: meta.thing_type,
    thing_id: meta.thing_id,
    address: meta.address,
    actions: {},
  };

  const actionNames = ['brightness', 'color_rgb', 'color_temp', 'effect', 'state'];
  for (const actionName of actionNames) {
    if (meta.actions && meta.actions[actionName]) {
      filtered.actions[actionName] = meta.actions[actionName];
    }
  }

  return filtered;
}

async function getThingsMeta(api_base_path, things) {
  // Fetch metadata for all things in parallel
  const metaPromises = things.map((thing) => {
    return new Promise((resolve) => {
      mJsonGet(`${api_base_path}/z2m/meta/${thing.thing_name}`, (meta) => {
        resolve({ name: thing.thing_name, meta: filterMeta(meta) });
      });
    });
  });

  const metaResults = await Promise.all(metaPromises);
  const metaByName = {};
  for (const result of metaResults) {
    metaByName[result.name] = result.meta;
  }
  return metaByName;
}

function buildGroupedThings(serverGroups, lights, switches, buttons) {
  // Build lookup maps
  const thingsByName = {};
  for (const light of lights) {
    thingsByName[light.thing_name] = { name: light.thing_name, type: 'light', data: light };
  }
  for (const sw of switches) {
    thingsByName[sw.thing_name] = { name: sw.thing_name, type: 'switch', data: sw };
  }

  // Assign buttons to groups by prefix match
  const buttonThings = [];
  for (const buttonObj of buttons) {
    const buttonName = Object.keys(buttonObj)[0];
    const buttonUrl = buttonObj[buttonName];
    buttonThings.push({ name: buttonName, type: 'button', data: { name: buttonName, url: buttonUrl } });
  }

  const groups = {};
  const sortedPrefixes = [];
  for (const g of serverGroups) {
    const members = g.lights
      .filter(name => thingsByName[name])
      .map(name => thingsByName[name])
      .sort((a, b) => a.name.localeCompare(b.name));
    // Add buttons whose name starts with this group prefix
    if (g.name !== 'Others') {
      for (const bt of buttonThings) {
        if (bt.name.startsWith(g.name)) {
          members.push(bt);
        }
      }
    }
    if (members.length > 0) {
      groups[g.name] = members;
      sortedPrefixes.push(g.name);
    }
  }

  // Add unassigned buttons to Others
  const assignedButtons = new Set();
  for (const prefix of sortedPrefixes) {
    for (const t of groups[prefix]) {
      if (t.type === 'button') assignedButtons.add(t.name);
    }
  }
  const unassignedButtons = buttonThings.filter(bt => !assignedButtons.has(bt.name));
  if (unassignedButtons.length > 0) {
    if (!groups['Others']) {
      groups['Others'] = [];
      sortedPrefixes.push('Others');
    }
    groups['Others'].push(...unassignedButtons);
  }

  // Ensure Others is last
  const idx = sortedPrefixes.indexOf('Others');
  if (idx >= 0 && idx < sortedPrefixes.length - 1) {
    sortedPrefixes.splice(idx, 1);
    sortedPrefixes.push('Others');
  }

  return { groups, sortedPrefixes };
}

// Props for the <li> of a thing: greyed out and not interactive while its network reports it offline
function thingAvailabilityProps(thing) {
  if (thing.available !== false) {
    return {};
  }
  return {
    style: { opacity: 0.4, pointerEvents: 'none' },
    title: `${thing.thing_name} is unavailable`,
  };
}

// Subtitle for an offline thing. z2m's last_seen may be an ISO string or epoch ms, depending on its config.
function offlineSubtitle(thing) {
  const seen = thing.last_seen != null ? new Date(thing.last_seen) : null;
  if (!seen || isNaN(seen)) return 'Offline';
  const sameDay = seen.toDateString() === new Date().toDateString();
  const when = sameDay
    ? seen.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : seen.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  return `Offline · last seen ${when}`;
}

// "FloorlampLeft" -> "Floorlamp left", "A_Dormir" -> "A dormir"
function prettyThingName(name) {
  return name.replace(/_/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .trim()
    .replace(/ ([A-Z])(?=[a-z])/g, (m, c) => ' ' + c.toLowerCase());
}

// z2m reports color temp in mireds; people think in Kelvin. Some lights use a 0-255 scale instead, show those raw.
function miredToKelvin(mired) {
  return mired >= 100 ? `${Math.round(1e6 / mired / 50) * 50} K` : String(mired);
}

// z2m may report "FFA7FF", a color input needs "#ffa7ff"
function normalizeRgb(rgb) {
  if (!rgb) return '#ffffff';
  return (rgb.startsWith('#') ? rgb : '#' + rgb).toLowerCase();
}

const ZL_RGB_SWATCHES = ['#ffffff', '#ff3b30', '#ff9500', '#ffd60a', '#34c759', '#00c7be', '#0a84ff', '#bf5af2'];

// Material Icons "tune" and "expand_more" (Apache 2.0), inline so the page doesn't fetch anything
const ZL_ICON_TUNE = (
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17v2h6v-2H3zM3 5v2h10V5H3zm10 16v-2h8v-2h-8v-2h-2v6h2zM7 9v2H3v2h4v2h2V9H7zm14 4v-2H11v2h10zm-6-4h2V7h4V5h-4V3h-2v6z"/></svg>);
const ZL_ICON_EXPAND = (
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16.59 8.59 12 13.17 7.41 8.59 6 10l6 6 6-6z"/></svg>);

class ZmwLight extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      state: props.light.state,
      brightness: props.light.brightness,
      color_temp: props.light.color_temp,
      color_rgb: props.light.color_rgb || '#ffffff',
      effect: props.light.effect,
      settingsOpen: false,
    };
  }

  componentDidUpdate(prevProps) {
    if (prevProps.light !== this.props.light) {
      this.setState({
        state: this.props.light.state,
        brightness: this.props.light.brightness,
        color_temp: this.props.light.color_temp,
        color_rgb: this.props.light.color_rgb || '#ffffff',
        effect: this.props.light.effect,
      });
    }
  }

  onStateChange(e) {
    const v = e.target.checked;
    this.setState({ state: v });
    mJsonPut(`${this.props.api_base_path}/z2m/set/${this.props.light.thing_name}`, {state: v});
  }

  onBrightnessChange(e) {
    const v = e.target.value;
    if (v == 0) {
      this.setState({ brightness: 0, state: false });
    } else {
      this.setState({ brightness: v, state: true });
    }
    mJsonPut(`${this.props.api_base_path}/z2m/set/${this.props.light.thing_name}`, {brightness: v});
  }

  onColorTempChange(e) {
    const v = e.target.value;
    this.setState({ color_temp: v });
    mJsonPut(`${this.props.api_base_path}/z2m/set/${this.props.light.thing_name}`, {color_temp: v});
  }

  onColorRgbChange(e) {
    const v = e.target.value;
    this.setState({ color_rgb: v });
    mJsonPut(`${this.props.api_base_path}/z2m/set/${this.props.light.thing_name}`, {color_rgb: v});
  }

  onEffectChange(e) {
    const v = e.target.value;
    this.setState({ effect: v });
    mJsonPut(`${this.props.api_base_path}/z2m/set/${this.props.light.thing_name}`, {effect: v});
  }

  renderColorTemp() {
    const meta = this.props.meta;
    if (!meta.actions.color_temp) {
      return null;
    }

    const colorTempMeta = meta.actions.color_temp.value.meta;
    const colorTemp = this.state.color_temp ?? Math.round((colorTempMeta.value_min + colorTempMeta.value_max) / 2);
    // Some bulbs report the same value under several names (eg Tradfri's coolest and cool), show each value once
    const presets = (colorTempMeta.presets || []).filter(
      (preset, idx, all) => all.findIndex(p => p.value === preset.value) === idx);

    return (
      <div className="zl-field">
        <div>Color temperature<span>{miredToKelvin(colorTemp)}</span></div>
        <DebouncedRange
          className="zl-ct"
          min={colorTempMeta.value_min}
          max={colorTempMeta.value_max}
          value={colorTemp}
          onChange={(e) => this.onColorTempChange(e)}
        />
        {presets.length > 0 && (
          <div className="zl-presets">
            {presets.map((preset) => (
              <button key={preset.value} type="button" aria-pressed={Number(colorTemp) === preset.value}
                      onClick={() => this.onColorTempChange({ target: { value: preset.value } })}>
                {preset.name}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  renderColorRgb() {
    const meta = this.props.meta;
    if (!meta.actions.color_rgb) {
      return null;
    }

    const rgb = normalizeRgb(this.state.color_rgb);
    return (
      <div className="zl-field">
        <div>Color<span>{rgb.toUpperCase()}</span></div>
        <div className="zl-swatches">
          {ZL_RGB_SWATCHES.map((color) => (
            <button key={color} type="button" style={{ background: color }} aria-label={`Color ${color}`}
                    aria-pressed={rgb === color}
                    onClick={() => this.onColorRgbChange({ target: { value: color } })} />
          ))}
          <label title="Custom color">
            <input type="color" aria-label="Custom color" value={rgb} onChange={(e) => this.onColorRgbChange(e)} />
          </label>
        </div>
      </div>
    );
  }

  renderEffect() {
    const meta = this.props.meta;
    if (!meta.actions.effect) {
      return null;
    }

    const effectValues = meta.actions.effect.value.meta.values || [];

    return (
      <div className="zl-field">
        <div>Effect</div>
        <select value={this.state.effect || ''} onChange={(e) => this.onEffectChange(e)}>
          <option value="">None</option>
          {effectValues.map((effect) => (
            <option key={effect} value={effect}>{effect}</option>
          ))}
        </select>
      </div>
    );
  }

  // Every bulb reports effects, even plain white ones: only those with color controls get a settings panel,
  // unless showAllSettings is set (the standalone lights page, where effects should stay reachable)
  hasSettings() {
    const actions = this.props.meta?.actions;
    if (!actions) return false;
    return !!(actions.color_temp || actions.color_rgb || (this.props.showAllSettings && actions.effect));
  }

  renderSettingsPanel() {
    const meta = this.props.meta;
    return (
      <div className="zl-panel">
        <div className="zl-dev">{meta.description} ({meta.model})</div>
        {this.renderColorTemp()}
        {this.renderColorRgb()}
        {this.renderEffect()}
      </div>
    );
  }

  renderSubtitle() {
    const light = this.props.light;
    if (light.available === false) return offlineSubtitle(light);
    if (!this.state.state) return 'Off';
    if (this.state.brightness == null) return 'On';
    const pct = Math.max(1, Math.round(this.state.brightness / 254 * 100));
    const hasColorTemp = this.props.meta?.actions?.color_temp && this.state.color_temp != null;
    return hasColorTemp ? `${pct}% · ${miredToKelvin(this.state.color_temp)}` : `${pct}%`;
  }

  render() {
    const light = this.props.light;
    const displayName = light.thing_name.startsWith(this.props.prefix)
      ? light.thing_name.slice(this.props.prefix.length)
      : light.thing_name;
    const inputId = `${light.thing_name}_light_is_on`;
    return (
      <div className={this.state.state ? 'zl-row' : 'zl-row zl-off'} {...thingAvailabilityProps(light)}>
        <label className="zl-name" htmlFor={inputId}>
          {prettyThingName(displayName)}<small>{this.renderSubtitle()}</small>
        </label>
        {this.hasSettings() ? (
          <button type="button" className="zl-more" aria-expanded={this.state.settingsOpen}
                  aria-label={`${displayName}: more settings`}
                  onClick={() => this.setState(s => ({ settingsOpen: !s.settingsOpen }))}>
            {ZL_ICON_TUNE}{ZL_ICON_EXPAND}
          </button>
        ) : <span />}
        <input
          id={inputId}
          className="zl-sw"
          type="checkbox"
          checked={!!this.state.state}
          onChange={(e) => this.onStateChange(e)}
        />
        <DebouncedRange
          className="zl-bri"
          min={0}
          max={254}
          value={this.state.brightness}
          onChange={(e) => this.onBrightnessChange(e)}
        />
        {this.state.settingsOpen && this.renderSettingsPanel()}
      </div>
    );
  }
}

class ZmwButton extends React.Component {
  onClick() {
    mJsonPut(this.props.url, {});
  }

  render() {
    let displayName = this.props.name.startsWith(this.props.prefix)
      ? this.props.name.slice(this.props.prefix.length)
      : this.props.name;
    return (
      <button type="button" onClick={() => this.onClick()}>{prettyThingName(displayName)}</button>
    );
  }
}

class ZmwSwitch extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      state: props.switch.state,
    };
  }

  componentDidUpdate(prevProps) {
    if (prevProps.switch !== this.props.switch) {
      this.setState({
        state: this.props.switch.state,
      });
    }
  }

  onStateChange(e) {
    const v = e.target.checked;
    this.setState({ state: v });
    mJsonPut(`${this.props.api_base_path}/z2m/set/${this.props.switch.thing_name}`, {state: v});
  }

  render() {
    const sw = this.props.switch;
    const displayName = sw.thing_name.startsWith(this.props.prefix)
      ? sw.thing_name.slice(this.props.prefix.length)
      : sw.thing_name;
    const inputId = `${sw.thing_name}_switch_is_on`;
    return (
      <div className={this.state.state ? 'zl-row' : 'zl-row zl-off'} {...thingAvailabilityProps(sw)}>
        <label className="zl-name" htmlFor={inputId}>
          {prettyThingName(displayName)}<small>{sw.available === false ? offlineSubtitle(sw) : 'Switch'}</small>
        </label>
        <span />
        <input
          id={inputId}
          className="zl-sw"
          type="checkbox"
          checked={!!this.state.state}
          onChange={(e) => this.onStateChange(e)}
        />
      </div>
    );
  }
}

class MqttLights extends React.Component {
  // groupBadges: optional {groupName: text or [texts]} shown on each group's tile (eg the room's temperatures)
  // groupExtras: optional {groupName: element} shown in an open group after its lights (eg the room's speakers)
  static buildProps(api_base_path = '', buttons = [], groupBadges = {}, groupExtras = {}) {
    return {
      key: 'MqttLights',
      local_storage: new LocalStorageManager(),
      api_base_path: api_base_path,
      buttons: buttons,
      groupBadges: groupBadges,
      groupExtras: groupExtras,
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      lights: [],
      switches: [],
      meta: {},
      serverGroups: [],
      groups: {},
      sortedPrefixes: [],
      loading: true,
      openGroup: null,
    };
  }

  async componentDidMount() {
    this.fetchThings();
    this._connectWebSocket();
  }

  componentDidUpdate(prevProps) {
    if (prevProps.buttons !== this.props.buttons) {
      this.rebuildGroups();
    }
  }

  componentWillUnmount() {
    this._wsClosing = true;
    clearTimeout(this._wsRetryTimer);
    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }
  }

  on_app_became_visible() {
    if (this._ws?.readyState === WebSocket.OPEN) return;
    this.fetchThings();
    this._connectWebSocket();
  }

  _connectWebSocket() {
    clearTimeout(this._wsRetryTimer);
    if (this._ws) {
      this._ws.close();
    }
    if (this._wsUrl) {
      this._openWebSocket(this._wsUrl);
    } else {
      // Not mJsonGet: on errors we retry, so a popup per attempt would be noise (a net down still shows, via mNet)
      mAjax({
        url: `${this.props.api_base_path}/get_ws_url`,
        type: 'GET',
        dataType: 'JSON',
        success: (resp) => {
          this._wsUrl = resp.url;
          this._openWebSocket(resp.url);
        },
        error: (err) => {
          console.warn("Lights: can't get ws url, will retry", err);
          this._scheduleWsReconnect();
        },
      });
    }
  }

  _scheduleWsReconnect() {
    // While hidden, don't retry: on_app_became_visible reconnects
    clearTimeout(this._wsRetryTimer);
    this._wsRetryTimer = setTimeout(() => {
      if (!this._wsClosing && !document.hidden) this._connectWebSocket();
    }, 2000);
  }

  _openWebSocket(url) {
    const ws = new WebSocket(url);
    this._ws = ws;
    ws.onmessage = (e) => {
      const update = JSON.parse(e.data);
      // console.log('WS thing update:', update);
      this._applyThingUpdate(update);
    };
    ws.onclose = () => {
      // A replaced ws (closed by _connectWebSocket) must not reconnect, or it'd close its replacement
      if (this._wsClosing || this._ws !== ws) return;
      // A close doesn't say if the server went away or the net did: check, so a net down shows (and clears)
      if (!document.hidden) mNetProbe().catch(() => {});
      this._scheduleWsReconnect();
    };
  }

  _applyThingUpdate(update) {
    this.setState(prevState => {
      const name = update.thing_name;
      const newLights = prevState.lights.map(l =>
        l.thing_name === name ? { ...l, ...update } : l
      );
      const newSwitches = prevState.switches.map(s =>
        s.thing_name === name ? { ...s, ...update } : s
      );
      const { groups, sortedPrefixes } = buildGroupedThings(
        prevState.serverGroups, newLights, newSwitches, this.props.buttons || []
      );
      return { lights: newLights, switches: newSwitches, groups, sortedPrefixes };
    });
  }

  rebuildGroups() {
    const { groups, sortedPrefixes } = buildGroupedThings(
      this.state.serverGroups, this.state.lights, this.state.switches, this.props.buttons || []
    );
    this.setState({ groups, sortedPrefixes });
  }

  clearCache() {
    const storage = this.props.local_storage;
    storage.remove('zmw_things_hash');
    storage.remove('things_meta');
    this.fetchThings();
  }

  async fetchAndUpdateThings(type, endpoint) {
    const storage = this.props.local_storage;

    return new Promise(resolve => {
      mJsonGet(`${this.props.api_base_path}${endpoint}`, async (things) => {
        // Fetch metadata for these things
        const cachedHash = storage.get('zmw_things_hash', null);
        const cachedMeta = storage.cacheGet('things_meta') || {};

        // Check if we need fresh metadata
        const serverHashPromise = new Promise(r =>
          mJsonGet(`${this.props.api_base_path}/z2m/get_known_things_hash`, r)
        );
        const serverHash = await serverHashPromise;

        let metaForThings = {};
        if (cachedHash && cachedHash === serverHash) {
          // Use cached metadata for known things
          for (const thing of things) {
            if (cachedMeta[thing.thing_name]) {
              metaForThings[thing.thing_name] = cachedMeta[thing.thing_name];
            }
          }
          // Fetch metadata for any things not in cache
          const uncachedThings = things.filter(t => !cachedMeta[t.thing_name]);
          if (uncachedThings.length > 0) {
            const freshMeta = await getThingsMeta(this.props.api_base_path, uncachedThings);
            metaForThings = { ...metaForThings, ...freshMeta };
          }
        } else {
          // Hash changed, fetch all metadata fresh
          metaForThings = await getThingsMeta(this.props.api_base_path, things);
          storage.save('zmw_things_hash', serverHash);
        }

        // Merge into cached metadata
        const newCachedMeta = { ...cachedMeta, ...metaForThings };
        storage.cacheSave('things_meta', newCachedMeta);

        // Update state with new things and merged metadata
        this.setState(prevState => {
          const newState = {
            [type]: things,
            meta: { ...prevState.meta, ...metaForThings },
            loading: false,
          };
          // Rebuild groups with updated data
          const lights = type === 'lights' ? things : prevState.lights;
          const switches = type === 'switches' ? things : prevState.switches;
          const { groups, sortedPrefixes } = buildGroupedThings(
            prevState.serverGroups, lights, switches, this.props.buttons || []
          );
          newState.groups = groups;
          newState.sortedPrefixes = sortedPrefixes;
          return newState;
        });

        resolve(things);
      });
    });
  }

  fetchThings() {
    // Fetch groups from backend, then lights and switches
    mJsonGet(`${this.props.api_base_path}/get_groups`, (serverGroups) => {
      this.setState({ serverGroups }, () => {
        this.fetchAndUpdateThings('lights', '/get_lights');
        this.fetchAndUpdateThings('switches', '/get_switches');
      });
    });
  }

  render() {
    // Show loading only if we have no content yet
    const hasContent = this.state.sortedPrefixes.length > 0;
    if (this.state.loading && !hasContent) {
      return ( <div className="app-loading">Loading...</div> );
    }

    return (
      <div className="zl">
        {this.state.sortedPrefixes.map((prefix) => this.renderGroup(prefix))}
        { this.props.runningStandaloneApp && (
          <button onClick={() => this.clearCache()}>Clear cache</button>)}
      </div>
    );
  }

  // One tile per group: name, badge, a dot per light/switch and an on-count. Tapping it opens the group full-width
  // (tiles keep their order, only one group open at a time).
  renderGroup(prefix) {
    const things = this.state.groups[prefix] || [];
    const buttons = things.filter(t => t.type === 'button');
    const switches = things.filter(t => t.type === 'switch');
    const lights = things.filter(t => t.type === 'light');
    const toggles = [...switches, ...lights];
    const reachable = toggles.filter(t => t.data.available !== false);
    const onCount = reachable.filter(t => t.data.state).length;
    let summary = `${onCount} of ${reachable.length} on`;
    if (onCount === 0) summary = 'All off';
    else if (onCount === reachable.length) summary = 'All on';

    const isOpen = this.state.openGroup === prefix;
    const badges = [].concat((this.props.groupBadges || {})[prefix] || []);
    const extras = (this.props.groupExtras || {})[prefix];
    let className = 'zl-group';
    if (onCount > 0) className += ' zl-lit';
    if (isOpen) className += ' zl-open';

    return (
      <div key={prefix} className={className}>
        <button type="button" className="zl-ghead" aria-expanded={isOpen}
                onClick={() => this.setState({ openGroup: isOpen ? null : prefix })}>
          <span className="zl-gname">{prefix}</span>
          <span className="zl-gbadge">
            {badges.map((text, idx) => <span key={idx}>{text}</span>)}
          </span>
          <span className="zl-dots">
            {toggles.map((t) => {
              let dot = '';
              if (t.data.available === false) dot = 'zl-na';
              else if (t.data.state) dot = 'zl-on';
              return <i key={t.name} className={dot} />;
            })}
          </span>
          <span className="zl-gsum">{summary}</span>
        </button>
        {isOpen && (
          <div className="zl-gbody">
            <div className="zl-chips">
              {(prefix !== 'Others') && (
                <><ZmwButton key={`${prefix}_All_On`}
                           name={`${prefix}_All_On`}
                           prefix={prefix}
                           url={`${this.props.api_base_path}/all_lights_on/prefix/${prefix}`} />
                <ZmwButton key={`${prefix}_All_Off`}
                           name={`${prefix}_All_Off`}
                           prefix={prefix}
                           url={`${this.props.api_base_path}/all_lights_off/prefix/${prefix}`} /></>
              )}
              {buttons.map((t) => (
                <ZmwButton key={t.name} name={t.data.name} url={t.data.url} prefix={prefix} />
              ))}
            </div>
            {switches.map((t) => (
              <ZmwSwitch key={t.name} switch={t.data} prefix={prefix} api_base_path={this.props.api_base_path} />
            ))}
            {lights.map((t) => (
              <ZmwLight key={t.name} light={t.data} meta={this.state.meta[t.name]} prefix={prefix}
                        showAllSettings={this.props.runningStandaloneApp}
                        api_base_path={this.props.api_base_path} />
            ))}
            {extras && <><hr className="zl-sep" />{extras}</>}
          </div>
        )}
      </div>
    );
  }
}

class StandaloneMqttLights extends MqttLights {
  static buildProps(api_base_path = '', buttons = []) {
    const p = super.buildProps(api_base_path, buttons);
    p.runningStandaloneApp = true;
    return p;
  }
}
