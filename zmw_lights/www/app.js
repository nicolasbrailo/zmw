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

function getPrefixGroups(lightNames) {
  // Get valid prefixes for a name (split at uppercase letters, min 3 chars)
  function getValidPrefixes(name) {
    const prefixes = [];
    for (let i = 1; i < name.length; i++) {
      if (name[i] >= 'A' && name[i] <= 'Z') {
        const prefix = name.substring(0, i);
        if (prefix.length >= 3) {
          prefixes.push(prefix);
        }
      }
    }
    if (name.length >= 3) {
      prefixes.push(name);
    }
    return prefixes;
  }

  // Count occurrences of each prefix
  const prefixCounts = {};
  for (const name of lightNames) {
    for (const prefix of getValidPrefixes(name)) {
      prefixCounts[prefix] = (prefixCounts[prefix] || 0) + 1;
    }
  }

  // For each light, find the prefix with the most lights (>= 2)
  const groups = {};
  const assigned = new Set();

  for (const name of lightNames) {
    let bestPrefix = null;
    let bestCount = 1;

    for (const prefix of getValidPrefixes(name)) {
      if (prefixCounts[prefix] > bestCount) {
        bestPrefix = prefix;
        bestCount = prefixCounts[prefix];
      }
    }

    if (bestPrefix) {
      if (!groups[bestPrefix]) {
        groups[bestPrefix] = [];
      }
      groups[bestPrefix].push(name);
      assigned.add(name);
    }
  }

  // Put unassigned lights in "Others"
  const others = lightNames.filter(name => !assigned.has(name));
  if (others.length > 0) {
    groups['Others'] = others;
  }

  return groups;
}

function groupThingsByPrefix(things) {
  // things = [{ name: 'X', type: 'light'|'button'|'switch', ... }, ...]
  const names = things.map(t => t.name);
  const prefixGroups = getPrefixGroups(names);

  const thingsByName = {};
  for (const thing of things) {
    thingsByName[thing.name] = thing;
  }

  const groups = {};
  const sortedPrefixes = Object.keys(prefixGroups).sort((a, b) => {
    if (a === 'Others') return 1;
    if (b === 'Others') return -1;
    return a.localeCompare(b);
  });

  for (const prefix of sortedPrefixes) {
    groups[prefix] = prefixGroups[prefix]
      .map(name => thingsByName[name])
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  return groups;
}

function normalizeThings(lights, switches, buttons) {
  const things = [];

  // Add lights
  for (const light of lights) {
    things.push({
      name: light.thing_name,
      type: 'light',
      data: light,
    });
  }

  // Add switches
  for (const sw of switches) {
    things.push({
      name: sw.thing_name,
      type: 'switch',
      data: sw,
    });
  }

  // Add buttons
  for (const buttonObj of buttons) {
    const buttonName = Object.keys(buttonObj)[0];
    const buttonUrl = buttonObj[buttonName];
    things.push({
      name: buttonName,
      type: 'button',
      data: { name: buttonName, url: buttonUrl },
    });
  }

  return things;
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
    // Compute initial groups from buttons (available immediately via props)
    const initialThings = normalizeThings([], [], props.buttons || []);
    const initialGroups = groupThingsByPrefix(initialThings);
    this.state = {
      lights: [],
      switches: [],
      meta: {},
      groups: initialGroups,
      sortedPrefixes: Object.keys(initialGroups),
      loading: true,
    };
  }

  async componentDidMount() {
    this.fetchThings();
  }

  componentDidUpdate(prevProps) {
    // Re-compute groups if buttons prop changed
    if (prevProps.buttons !== this.props.buttons) {
      this.recomputeGroups();
    }
  }

  on_app_became_visible() {
    this.fetchThings();
  }

  recomputeGroups() {
    const allThings = normalizeThings(
      this.state.lights,
      this.state.switches,
      this.props.buttons || []
    );
    const groups = groupThingsByPrefix(allThings);
    this.setState({ groups, sortedPrefixes: Object.keys(groups) });
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
          };
          // Recompute groups with updated data
          const lights = type === 'lights' ? things : prevState.lights;
          const switches = type === 'switches' ? things : prevState.switches;
          const allThings = normalizeThings(lights, switches, this.props.buttons || []);
          const groups = groupThingsByPrefix(allThings);
          newState.groups = groups;
          newState.sortedPrefixes = Object.keys(groups);
          newState.loading = false;
          return newState;
        });

        resolve(things);
      });
    });
  }

  fetchThings() {
    // Fetch lights and switches independently - UI updates as each arrives
    this.fetchAndUpdateThings('lights', '/get_lights');
    this.fetchAndUpdateThings('switches', '/get_switches');
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
                {(prefix !== 'Others') && (
                  <li>
                    <ZmwButton key={`${prefix}_All_On`}
                               name={`${prefix}_All_On`}
                               prefix={prefix}
                               url={`${this.props.api_base_path}/all_lights_on/prefix/${prefix}`} />
                    <ZmwButton key={`${prefix}_All_Off`}
                               name={`${prefix}_All_Off`}
                               prefix={prefix}
                               url={`${this.props.api_base_path}/all_lights_off/prefix/${prefix}`} />
                  {buttons.map((t) => (
                    <ZmwButton key={t.name} name={t.data.name} url={t.data.url} prefix={prefix} />
                  ))}
                  </li>
                )}
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
