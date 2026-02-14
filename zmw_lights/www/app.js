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

class ZmwLight extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      state: props.light.state,
      brightness: props.light.brightness,
      color_temp: props.light.color_temp,
      color_rgb: props.light.color_rgb || '#ffffff',
      effect: props.light.effect,
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
    const presets = colorTempMeta.presets || [];

    return (
      <div>
      <label>Temperature</label>
      <DebouncedRange
        min={colorTempMeta.value_min}
        max={colorTempMeta.value_max}
        value={this.state.color_temp}
        onChange={(e) => this.onColorTempChange(e)}
      />
      <select value={this.state.color_temp} onChange={(e) => this.onColorTempChange(e)}>
        {presets.map((preset) => (
          <option key={preset.name} value={preset.value}>{preset.name}</option>
        ))}
      </select>
      </div>
    );
  }

  renderColorRgb() {
    const meta = this.props.meta;
    if (!meta.actions.color_rgb) {
      return null;
    }

    return (
      <div>
      <label>RGB</label>
      <input
        type="color"
        value={this.state.color_rgb}
        onChange={(e) => this.onColorRgbChange(e)}
      />
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
      <div>
      <label>Effect</label>
      <select value={this.state.effect || ''} onChange={(e) => this.onEffectChange(e)}>
        <option value="">None</option>
        {effectValues.map((effect) => (
          <option key={effect} value={effect}>{effect}</option>
        ))}
      </select>
      </div>
    );
  }

  renderExtraCfgs() {
    const meta = this.props.meta;
    if (!(meta.actions.color_temp || meta.actions.color_rgb || meta.actions.effect)) {
      return null;
    }

    return (
      <details className="light_details">
        <summary>⚙</summary>
        {meta.name} ({meta.description} / {meta.model})
        {this.renderColorTemp()}
        {this.renderColorRgb()}
        {this.renderEffect()}
      </details>
    );
  }


  render() {
    const light = this.props.light;
    const meta = this.props.meta;
    const displayName = light.thing_name.startsWith(this.props.prefix)
      ? light.thing_name.slice(this.props.prefix.length)
      : light.thing_name;
    return (
      <li>
        <input
          id={`${light.thing_name}_light_is_on`}
          type="checkbox"
          value="true"
          checked={this.state.state}
          onChange={(e) => this.onStateChange(e)}
        />
        <label htmlFor={`${light.thing_name}_light_is_on`}>{displayName}</label>
        <DebouncedRange
          min={0}
          max={254}
          value={this.state.brightness}
          onChange={(e) => this.onBrightnessChange(e)}
        />
        {this.renderExtraCfgs()}
      </li>
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
    displayName = displayName.replace(/_/g, ' ').trim();
    return (
      <button onClick={() => this.onClick()}>{displayName}</button>
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
    return (
      <li>
        <input
          id={`${sw.thing_name}_switch_is_on`}
          type="checkbox"
          value="true"
          checked={this.state.state}
          onChange={(e) => this.onStateChange(e)}
        />
        <label htmlFor={`${sw.thing_name}_switch_is_on`}>{displayName}</label>
      </li>
    );
  }
}

class MqttLights extends React.Component {
  static buildProps(api_base_path = '', buttons = []) {
    return {
      key: 'MqttLights',
      local_storage: new LocalStorageManager(),
      api_base_path: api_base_path,
      buttons: buttons,
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
    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }
  }

  on_app_became_visible() {
    this.fetchThings();
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) {
      this._connectWebSocket();
    }
  }

  _connectWebSocket() {
    if (this._ws) {
      this._ws.close();
    }
    if (this._wsUrl) {
      this._openWebSocket(this._wsUrl);
    } else {
      mJsonGet(`${this.props.api_base_path}/get_ws_url`, (resp) => {
        this._wsUrl = resp.url;
        this._openWebSocket(resp.url);
      });
    }
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
      if (!this._wsClosing) {
        setTimeout(() => this._connectWebSocket(), 2000);
      }
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
      <div id="zmw_lights">
        {this.state.sortedPrefixes.map((prefix) => {
          const things = this.state.groups[prefix] || [];
          const buttons = things.filter(t => t.type === 'button');
          const switches = things.filter(t => t.type === 'switch');
          const lights = things.filter(t => t.type === 'light');
          return (
            <details key={prefix}>
              <summary>{prefix}</summary>
              <ul>
                <li>
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
                </li>
                {switches.map((t) => (
                  <ZmwSwitch key={t.name} switch={t.data} prefix={prefix} api_base_path={this.props.api_base_path} />
                ))}
                {lights.map((t) => (
                  <ZmwLight key={t.name} light={t.data} meta={this.state.meta[t.name]} prefix={prefix} api_base_path={this.props.api_base_path} />
                ))}
              </ul>
            </details>
          );
        })}
        { this.props.runningStandaloneApp && (
          <button onClick={() => this.clearCache()}>Clear cache</button>)}
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
