class DoorMan extends React.Component {
  static buildProps(api_base_path = '') {
    return {
      key: 'DoorMan',
      api_base_path: api_base_path,
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      stats: null,
      snapLoading: false,
      snapKey: 0,
      skipChimesRemaining: null,
    };
    this.skipChimesInterval = null;
    this.fetchStats = this.fetchStats.bind(this);
    this.requestSnap = this.requestSnap.bind(this);
    this.openCamsService = this.openCamsService.bind(this);
    this.openContactmonService = this.openContactmonService.bind(this);
    this.skipChimes = this.skipChimes.bind(this);
    this.fetchContactmonState = this.fetchContactmonState.bind(this);
    this.handleContactmonState = this.handleContactmonState.bind(this);
  }

  async componentDidMount() {
    this.fetchStats();
    this.fetchContactmonState();
  }

  componentWillUnmount() {
    if (this.skipChimesInterval) {
      clearInterval(this.skipChimesInterval);
    }
  }

  on_app_became_visible() {
    this.fetchStats();
    this.fetchContactmonState();
  }

  fetchStats() {
    mJsonGet(`${this.props.api_base_path}/stats`, (res) => {
      this.setState({ stats: res });
    });
  }

  requestSnap() {
    this.setState({ snapLoading: true, snapKey: this.state.snapKey + 1 });
    fetch(`${this.props.api_base_path}/request_snap`, { method: 'PUT' });
    setTimeout(() => {
      this.setState({ snapLoading: false, snapKey: this.state.snapKey + 1 });
      this.fetchStats();
    }, 1500);
  }

  openLinkedService(url_cb) {
    mJsonGet(`${this.props.api_base_path}${url_cb}`, (res) => {
      if (res.url) {
        window.open(res.url, '_blank');
      } else {
        showGlobalError("Service has no known URL");
      }
    });
  }

  openCamsService() { this.openLinkedService('/get_cams_svc_url'); }
  openContactmonService() { this.openLinkedService('/get_contactmon_svc_url'); }

  fetchContactmonState() {
    mJsonGet(`${this.props.api_base_path}/contactmon_state`, (res) => {
      this.handleContactmonState(res);
    });
  }

  handleContactmonState(res) {
    if (this.skipChimesInterval) {
      clearInterval(this.skipChimesInterval);
      this.skipChimesInterval = null;
    }

    if (res.skipping_chimes && res.skipping_chimes_timeout_secs) {
      this.setState({ skipChimesRemaining: Math.ceil(res.skipping_chimes_timeout_secs) });
      this.skipChimesInterval = setInterval(() => {
        this.setState((prevState) => {
          const remaining = prevState.skipChimesRemaining - 1;
          if (remaining <= 0) {
            clearInterval(this.skipChimesInterval);
            this.skipChimesInterval = null;
            this.fetchContactmonState();
            return { skipChimesRemaining: null };
          }
          return { skipChimesRemaining: remaining };
        });
      }, 1000);
    } else {
      this.setState({ skipChimesRemaining: null });
    }
  }

  skipChimes() {
    fetch(`${this.props.api_base_path}/skip_chimes`, { method: 'PUT' })
      .then(res => res.json())
      .then(res => {
        if (res.error || !res.skipping_chimes_timeout_secs) {
          showGlobalError("Can't skip chimes");
          return;
        }
        this.handleContactmonState(res);
      });
  }

  formatTimestamp(ts) {
    if (!ts) return '?';
    const date = new Date(ts * 1000);
    return date.toLocaleString();
  }

  formatDuration(secs) {
    if (secs === null || secs === undefined) return '?';
    if (secs < 60) return `${secs.toFixed(1)}s`;
    const mins = Math.floor(secs / 60);
    const remainingSecs = secs % 60;
    return `${mins}m ${remainingSecs.toFixed(0)}s`;
  }

  renderHistory(history) {
    if (!history || history.length === 0) {
      return <p>No events recorded</p>;
    }
    return (
      <table>
        <thead>
          <tr><th>Type</th><th>Time</th><th>Duration</th><th>Snap</th></tr>
        </thead>
        <tbody>
          {history.map((e, i) => (
            <tr key={i}>
              <td>{e.event_type}</td>
              <td>{this.formatTimestamp(e.time)}</td>
              <td>{e.duration_secs !== undefined ? this.formatDuration(e.duration_secs) : '-'}</td>
              <td>{e.snap ? <a href={`${this.props.api_base_path}/get_snap/${e.snap}`} target="_blank">{e.snap}</a> : '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  render() {
    const { stats } = this.state;

    if (!stats) {
      return <div>Loading...</div>;
    }

    return (
      <div>
        <button onClick={this.requestSnap} disabled={this.state.snapLoading}>
          <img src={`${this.props.api_base_path}/new_snap.ico`} />
          {this.state.snapLoading ? 'Loading...' : 'New Snap'}
        </button>
        <button onClick={this.openCamsService}>
          <img src={`${this.props.api_base_path}/cams.ico`} />Cameras
        </button>
        <button onClick={this.openContactmonService}>
          <img src={`${this.props.api_base_path}/contactmon.ico`} />Contact
        </button>
        <button className={this.state.skipChimesRemaining? "warn" : ""} onClick={this.skipChimes}>
          <img src={`${this.props.api_base_path}/silence.ico`} />
          { this.state.skipChimesRemaining ?
            `Skipping chimes (${this.state.skipChimesRemaining}s)` :
            'Skip chimes' }
        </button>
        {stats.last_snap && (
          <div>
            {!this.state.snapLoading && (
              <a href={`${this.props.api_base_path}/get_snap/${stats.last_snap}`} target="_blank">
                <img key={this.state.snapKey} 
                     src={`${this.props.api_base_path}/get_snap/${stats.last_snap}?t=${this.state.snapKey}`}
                     alt="Last snap" style={{maxWidth: '100%', maxHeight: '300px'}} />
              </a>
            )}
          </div>
        )}
        <div className={stats.door_open_in_progress || stats.motion_in_progress? "card warn" : "card hint"}>
          <p>{stats.door_open_in_progress? "Door open" : "Door closed"}
            {stats.motion_in_progress ? ', motion detected' : ''}
          </p>
          <p>Today: Doorbell rang {stats.doorbell_press_count_today} times, {stats.motion_detection_count_today} motion events.
             Snap @ {this.formatTimestamp(stats.last_snap_time)}</p>
        </div>

        <details>
        <summary>History</summary>
        {this.renderHistory(stats.history)}
        </details>
      </div>
    );
  }
}
function millisecToNextSlotChg() {
  const now = new Date();
  const qr = Math.floor(now.getMinutes() / 15);
  const nxt_slot_chg_min = (15 * (qr + 1)) % 60;
  const slot_chg = new Date();
  slot_chg.setMinutes(nxt_slot_chg_min);
  slot_chg.setSeconds(0);
  const ms_to_chg = (slot_chg - now);

  if (nxt_slot_chg_min == 0) {
    // If we're rolling over to start of the hour, add one hour
    return ms_to_chg + 60 * 60 * 1000;
  }

  return ms_to_chg;
}

function renderScheduleTable(sched, slotGenerator) {
  const qr_groupped_sched = {};
  for (let hr=0; hr<24; ++hr) {
    qr_groupped_sched[hr] = sched.slice(hr*4,(hr+1)*4);
  }
  return (
    <table>
    <tbody>
    {Object.keys(qr_groupped_sched).map((hour) => {
      return (<tr key={`table_schedule_${hour}`}>
        {qr_groupped_sched[hour].map((slot) => {
          return <td key={`table_schedule_${slot.hour}_${slot.minute}`} data-state={slot.request_on ? 'on' : 'off'}>
                  {slotGenerator(slot)}
                 </td>;
        })}
      </tr>);
    })}
    </tbody>
    </table>
  );
}

class HeatingControls extends React.Component {
  static buildProps(api_base_path = '', state = {}) {
    const props = {
      api_base_path: api_base_path,
    };

    // Optional: pass state data to avoid fetching if already available
    if (state.allow_on !== undefined) props.allow_on = state.allow_on;
    if (state.mqtt_thing_reports_on !== undefined) props.mqtt_thing_reports_on = state.mqtt_thing_reports_on;
    if (state.monitoring_sensors !== undefined) props.monitoring_sensors = state.monitoring_sensors;
    if (state.onRefresh !== undefined) props.onRefresh = state.onRefresh;

    return props;
  }

  constructor(props) {
    super(props);
    this._offNow = this._offNow.bind(this);
    this._refresh = this._refresh.bind(this);

    this.state = {
      allow_on: props.allow_on || null,
      mqtt_thing_reports_on: props.mqtt_thing_reports_on || null,
      monitoring_sensors: props.monitoring_sensors || null,
    };
  }

  componentDidMount() {
    // If no data provided via props, fetch it
    if (!this.props.allow_on && this.props.api_base_path) {
      this._refresh();
    }
  }

  componentDidUpdate(prevProps) {
    // Update internal state if props change
    if (prevProps.allow_on !== this.props.allow_on ||
        prevProps.mqtt_thing_reports_on !== this.props.mqtt_thing_reports_on ||
        prevProps.monitoring_sensors !== this.props.monitoring_sensors) {
      this.setState({
        allow_on: this.props.allow_on,
        mqtt_thing_reports_on: this.props.mqtt_thing_reports_on,
        monitoring_sensors: this.props.monitoring_sensors,
      });
    }
  }

  _refresh() {
    if (this.props.api_base_path) {
      mJsonGet(`${this.props.api_base_path}/svc_state`, state => {
        this.setState({
          allow_on: state.allow_on,
          mqtt_thing_reports_on: state.mqtt_thing_reports_on,
          monitoring_sensors: state.monitoring_sensors,
        });
        if (this.props.onRefresh) {
          this.props.onRefresh();
        }
      });
    }
  }

  _mkBoost(hours) {
    return () => {
      mJsonGet(`${this.props.api_base_path}/boost=${hours}`, this._refresh);
    };
  }

  _offNow() {
    mJsonGet(`${this.props.api_base_path}/off_now`, this._refresh);
  }

  renderHeatingOverrides() {
    let policy_state = "Boiler manager unknown state";
    if (this.state.allow_on == 'Never') {
      policy_state = "Boiler should be off";
    } else if (this.state.allow_on == 'Always') {
      policy_state = "Boiler should be on";
    } else if (this.state.allow_on == 'Rule') {
      policy_state = "Rule controls boiler state";
    }
    return <div className="card hint">
        <p><b>Current status: {policy_state}, boiler reports {this.state.mqtt_thing_reports_on}</b></p>
        <button onClick={this._mkBoost(1)}>Boost 1 hour</button>
        <button onClick={this._mkBoost(2)}>Boost 2 hours</button>
        <button onClick={this._offNow}>Off now</button>
      </div>
  }

  renderMonitoringSensors() {
    if (!this.state.monitoring_sensors) {
      return (<div className="card hint">
              <p>Loading sensors!</p>
              <p>Please wait...</p>
              </div>)
    }
    return (
      <ul className="not-a-list">
        {Object.entries(this.state.monitoring_sensors).map(([name, value]) => (
          <li key={name} className="infobadge">
            {name}: {`${value}°C` || '? °C'}
          </li>
        ))}
      </ul>
    );
  }

  render() {
    return <>
      {this.renderHeatingOverrides()}
      {this.renderMonitoringSensors()}
    </>;
  }
}

class HeatingScheduleConfig extends React.Component {
  static buildProps(api_base_path = '', onRefresh = null, onToggleConfig = null, state = {}, renderFunctions = {}) {
    return {
      api_base_path: api_base_path,
      onRefresh: onRefresh,
      onToggleConfig: onToggleConfig,
      configuring: state.configuring || false,
      active_schedule: state.active_schedule || null,
      schedule_template: state.schedule_template || null,
      renderSlot: renderFunctions.renderSlot || null,
      renderTemplateSlot: renderFunctions.renderTemplateSlot || null,
    };
  }

  constructor(props) {
    super(props);
    this._applyTemplate = this._applyTemplate.bind(this);
    this._resetTemplateAlwaysOff = this._resetTemplateAlwaysOff.bind(this);
    this._resetTemplateAlwaysRule = this._resetTemplateAlwaysRule.bind(this);
    this._showLogs = this._showLogs.bind(this);
  }

  _applyTemplate() {
    mJsonGet(`${this.props.api_base_path}/template_apply`, this.props.onRefresh);
  }

  _resetTemplateAlwaysOff() {
    mJsonGet(`${this.props.api_base_path}/template_reset=Never`, this.props.onRefresh);
  }

  _resetTemplateAlwaysRule() {
    mJsonGet(`${this.props.api_base_path}/template_reset=Rule`, this.props.onRefresh);
  }

  _showLogs() {
    window.open('/logs.html', '_self');
  }

  renderConfig() {
    if (!this.props.schedule_template) {
      return null;
    }
    return <div>
        {this.renderTemplateControls()}
        {renderScheduleTable(this.props.schedule_template, this.props.renderTemplateSlot)}
      </div>;
  }

  renderState() {
    if (!this.props.active_schedule) {
      return null;
    }
    return <div>
      {renderScheduleTable(this.props.active_schedule, this.props.renderSlot)}
      {this.renderConfigControls()}
    </div>
  }

  renderConfigControls() {
    return <div className="card">
        <button onClick={this.props.onToggleConfig}>Config</button>
        <button onClick={this._applyTemplate}>Reset today schedule</button>
        <button onClick={this._showLogs}>Logs</button>
      </div>
  }

  renderTemplateControls() {
    return <div className="card">
        <button onClick={this.props.onToggleConfig}>Finish Config</button>
        <button onClick={this._applyTemplate}>Apply template / reset today schedule</button>
        <button onClick={this._resetTemplateAlwaysOff}>Reset template: Always off</button>
        <button onClick={this._resetTemplateAlwaysRule}>Reset template: Always rule-based</button>
      </div>
  }

  render() {
    return this.props.configuring ? this.renderConfig() : this.renderState();
  }
}

class MqttHeating extends React.Component {
  static buildProps(api_base_path = '') {
    return {
      key: 'HeatingPane',
      api_base_path: api_base_path,
    };
  }

  constructor(props) {
    super(props);
    this.refresh = this.refresh.bind(this);
    this._toggleConfig = this._toggleConfig.bind(this);
    this._renderSlot = this._renderSlot.bind(this);
    this._renderTemplateSlot = this._renderTemplateSlot.bind(this);

    const app_visibility = new VisibilityCallback();
    app_visibility.app_became_visible = this.refresh;

    this.state = {
      configuring: false,
      active_schedule: null,
      schedule_template: null,
      allow_on: null,
      mqtt_thing_reports_on: null,
      monitoring_sensors: null,
      refreshId: null,
      app_visibility,
    };
  }

  refresh() {
    if (this.state.refreshId) {
      // Calling clearTimeout with an invalid id doesn't throw an error
      clearTimeout(this.state.refreshId);
    }

    if (this.state.configuring) {
      console.log("Configuring: will refresh schedule");
      mJsonGet(`${this.props.api_base_path}/template_schedule`, tmpl_state => {
        this.setState({schedule_template: tmpl_state.template});
      });
      return;
    }

    console.log("Refreshing boiler state...");
    mJsonGet(`${this.props.api_base_path}/svc_state`, state => {
      this.setState({active_schedule: state.active_schedule,
                     allow_on: state.allow_on,
                     mqtt_thing_reports_on: state.mqtt_thing_reports_on,
                     monitoring_sensors: state.monitoring_sensors,
                     refreshId: setInterval(this.refresh, millisecToNextSlotChg())});
    });
  }

  _toggleConfig() {
    this.setState({configuring: !this.state.configuring});
  }

  render() {
    return this.state.configuring? this.renderConfig() : this.renderState();
  }

  renderConfig() {
    if (!this.state.schedule_template) {
      this.refresh();
      return "Loading configuration...";
    }
    return <div>
      <HeatingScheduleConfig
        configuring={true}
        schedule_template={this.state.schedule_template}
        renderTemplateSlot={this._renderTemplateSlot}
        api_base_path={this.props.api_base_path}
        onRefresh={this.refresh}
        onToggleConfig={this._toggleConfig}
      />
    </div>;
  }

  renderState() {
    if (!this.state.active_schedule) {
      this.refresh();
      return "Loading...";
    }

    return <div>
      <HeatingControls
        allow_on={this.state.allow_on}
        mqtt_thing_reports_on={this.state.mqtt_thing_reports_on}
        monitoring_sensors={this.state.monitoring_sensors}
        api_base_path={this.props.api_base_path}
        onRefresh={this.refresh}
      />
      <HeatingScheduleConfig
        configuring={false}
        active_schedule={this.state.active_schedule}
        renderSlot={this._renderSlot}
        api_base_path={this.props.api_base_path}
        onRefresh={this.refresh}
        onToggleConfig={this._toggleConfig}
      />
    </div>
  }

  _renderSlot(slot) {
    const slot_name = `${('0' + slot.hour).slice(-2)}:${('0' + slot.minute).slice(-2)}`;
    const cb = () => {
      console.log("User toggling slot", slot_name);
      mJsonGet(`${this.props.api_base_path}/slot_toggle=${slot_name}`, this.refresh)
    };

    let descr = "Error";
    if (slot.allow_on == 'Never') {
      descr = `Off: ${slot.reason}`
    } else if (slot.allow_on == 'Always') {
      descr = `On: ${slot.reason}`
    } else if (slot.allow_on == 'Rule' && slot.request_on) {
      descr = `On: Rule ${slot.reason}`
    } else if (slot.allow_on == 'Rule' && !slot.request_on) {
      descr = `Off: Rule ${slot.reason}`
    }

    return <button onClick={cb}>
             {slot_name}<wbr/> {descr}
           </button>
  }

  _renderTemplateSlot(slot) {
    const slot_name = `${('0' + slot.hour).slice(-2)}:${('0' + slot.minute).slice(-2)}`;
    const cb = (evt) => {
      const selected = evt.nativeEvent.target.value;
      console.log("Uset setting template", slot_name, selected);
      mJsonGet(`${this.props.api_base_path}/template_slot_set=${slot.hour},${slot.minute},${selected}`, this.refresh)
    };

    return <div>
            {slot_name}<wbr/> {slot.reason}
            <select key="`table_schedule_${slot.hour}_${slot.minute}_opt`"
                    defaultValue={slot.allow_on}
                    onChange={cb}>
              <option value="Always">Always on</option>
              <option value="Never">Always off</option>
              <option value="Rule">Follow rule</option>
            </select>
      </div>
  }
}
// Hardcoded list of actions to display
const EXPECTED_ACTIONS = [
  'child_lock',
  'error',
  'feeding_size',
  'feeding_source',
  'led_indicator',
  'mode',  // feeding_mode in UI
  'portion_weight',
  'portions_per_day',
  'serving_size',
  'weight_per_day',
];

class CatFeeder extends React.Component {
  static buildProps(api_base_path = '') {
    return {
      key: 'CatFeeder',
      api_base_path: api_base_path,
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      loading: true,
      errors: [],
      thingName: null,
      metadata: null,
      actionValues: {},
      originalValues: {},
      feedHistory: [],
      feedSchedule: [],
      editableSchedule: [],
      newEntryHour: 0,
      newEntryMinute: 0,
      newEntryServingSize: 1,
    };
    this.settingsRef = React.createRef();
  }

  async componentDidMount() {
    await this.fetchDeviceList();
    await this.fetchHistory();
    await this.fetchSchedule();
  }

  async fetchHistory() {
    return new Promise((resolve) => {
      mJsonGet(`${this.props.api_base_path}/feed_history`, (history) => {
        this.setState({ feedHistory: history || [] });
        resolve();
      });
    });
  }

  async fetchSchedule() {
    return new Promise((resolve) => {
      mJsonGet(`${this.props.api_base_path}/feed_schedule`, (schedule) => {
        const scheduleData = schedule || [];
        this.setState({
          feedSchedule: scheduleData,
          editableSchedule: scheduleData.map(entry => ({ ...entry })),
        });
        resolve();
      });
    });
  }

  handleDeleteScheduleEntry(index) {
    this.setState((prevState) => ({
      editableSchedule: prevState.editableSchedule.filter((_, i) => i !== index),
    }));
  }

  handleAddScheduleEntry() {
    const { newEntryHour, newEntryMinute, newEntryServingSize } = this.state;
    const newEntry = {
      days: 'everyday',
      hour: newEntryHour,
      minute: newEntryMinute,
      serving_size: newEntryServingSize,
    };
    this.setState((prevState) => ({
      editableSchedule: [...prevState.editableSchedule, newEntry],
      newEntryHour: 0,
      newEntryMinute: 0,
      newEntryServingSize: 1,
    }));
  }

  handleSaveSchedule() {
    const { editableSchedule } = this.state;
    const payload = editableSchedule.map(entry => ({
      days: entry.days || 'everyday',
      hour: entry.hour,
      minute: entry.minute,
      serving_size: entry.serving_size,
    }));
    mJsonPut('/save_schedule', payload);
  }

  handleFeedNow() {
    mJsonGet(`${this.props.api_base_path}/feed_now?source=www`, () => {
      this.fetchHistory();
    });
  }

  on_app_became_visible() {
    // No action on refresh, devices shouldn't change that much
  }

  async fetchDeviceList() {
    return new Promise((resolve) => {
      mJsonGet(`${this.props.api_base_path}/z2m/ls`, async (devices) => {
        const errors = [];

        if (!Array.isArray(devices) || devices.length === 0) {
          errors.push('No device found! Cat will be angry.');
          this.setState({ loading: false, errors });
          resolve();
          return;
        }

        if (devices.length != 1) {
          errors.push(`Expected 1 device, found ${devices.length}. Using first device.`);
        }

        const thingName = devices[0];
        this.setState({ thingName, errors }, () => {
          this.fetchMetadata(thingName).then(resolve);
        });
      });
    });
  }

  async fetchMetadata(thingName) {
    return new Promise((resolve) => {
      mJsonGet(`${this.props.api_base_path}/z2m/meta/${thingName}`, (metadata) => {
        const errors = [...this.state.errors];
        const actionValues = {};

        // Validate expected actions exist
        for (const actionName of EXPECTED_ACTIONS) {
          if (!metadata.actions || !metadata.actions[actionName]) {
            errors.push(`Missing expected action: ${actionName}`);
          } else {
            // Initialize action values from metadata
            const action = metadata.actions[actionName];
            actionValues[actionName] = action.value._current;
          }
        }

        // Check error action
        if (metadata.actions && metadata.actions.error) {
          const errorAction = metadata.actions.error;
          const errorValue = errorAction.value._current;
          const valueOn = errorAction.value.meta.value_on;
          if (errorValue === valueOn || errorValue === true) {
            errors.push(`${thingName} reports an error, check the device`);
          }
        }

        this.setState({
          loading: false,
          metadata,
          actionValues,
          originalValues: { ...actionValues },
          errors,
        });
        resolve();
      });
    });
  }

  handleActionChange(actionName, value) {
    this.setState((prevState) => ({
      actionValues: {
        ...prevState.actionValues,
        [actionName]: value,
      },
    }));
  }

  handleSave() {
    const { thingName, metadata, actionValues, originalValues } = this.state;
    if (!thingName || !metadata) return;

    // Build the payload with only settable actions that changed and have a value
    const payload = {};
    for (const actionName of EXPECTED_ACTIONS) {
      const action = metadata.actions[actionName];
      if (!action || !action.can_set) continue;

      const currentValue = actionValues[actionName];
      const originalValue = originalValues[actionName];

      // Skip if value is null/undefined or hasn't changed
      if (currentValue === null || currentValue === undefined) continue;
      if (currentValue === '' && (originalValue === null || originalValue === undefined)) continue;
      if (currentValue === originalValue) continue;

      payload[actionName] = currentValue;
    }

    // Don't send empty payload
    if (Object.keys(payload).length === 0) return;

    mJsonPut(`${this.props.api_base_path}/z2m/set/${thingName}`, payload);

    if (this.settingsRef.current) {
      this.settingsRef.current.open = false;
    }
  }

  renderActionInput(actionName, action) {
    const { actionValues } = this.state;
    const meta = action.value.meta;
    const currentValue = actionValues[actionName];

    if (!action.can_set) {
      // Read-only display
      if (meta.type === 'binary') {
        const isOn = currentValue === meta.value_on || currentValue === true;
        return <span>{isOn ? 'Yes' : 'No'}</span>;
      }
      return <span>{currentValue !== null ? String(currentValue) : '-'}</span>;
    }

    // Editable inputs
    if (meta.type === 'binary') {
      const isChecked = currentValue === meta.value_on || currentValue === true;
      return (
        <input
          type="checkbox"
          checked={isChecked}
          onChange={(e) => {
            const newValue = e.target.checked ? meta.value_on : meta.value_off;
            this.handleActionChange(actionName, newValue);
          }}
        />
      );
    }

    if (meta.type === 'numeric') {
      if (meta.value_min !== null && meta.value_max !== null) {
        const displayValue = currentValue !== null ? currentValue : meta.value_min;
        return (
          <>
            <input
              type="range"
              min={meta.value_min}
              max={meta.value_max}
              value={displayValue}
              onChange={(e) => {
                this.handleActionChange(actionName, Number(e.target.value));
              }}
            />
            <span>{displayValue}</span>
          </>
        );
      }
      return (
        <input
          type="text"
          value={currentValue !== null ? currentValue : ''}
          onChange={(e) => {
            const val = e.target.value === '' ? null : Number(e.target.value);
            this.handleActionChange(actionName, val);
          }}
        />
      );
    }

    if (meta.type === 'enum') {
      return (
        <select
          value={currentValue !== null ? currentValue : ''}
          onChange={(e) => this.handleActionChange(actionName, e.target.value)}
        >
          <option value="">--Select--</option>
          {meta.values.map((val) => (
            <option key={val} value={val}>{val}</option>
          ))}
        </select>
      );
    }

    return <span>{currentValue !== null ? String(currentValue) : '-'}</span>;
  }

  render() {
    if (this.state.loading) {
      return <div className="app-loading">Loading...</div>;
    }

    return (
      <section id="CatFeederContainer">
        {(this.state.errors.length !== 0) && (
          <div>
            {this.state.errors.map((error, index) => (
              <div key={index} className="card warn">
                <p>Error!</p>
                <p>{error}</p>
              </div>
            ))}
          </div>
        )}

        { (!this.state.metadata || !this.state.metadata.actions)? (
          <div className="card hint">
            <p>Device loading...</p>
          </div>
        ) : (
          <>
          <div className="card hint">
            <p>{this.state.metadata.name}</p>
            <p>{this.state.metadata.description} {this.state.metadata.model}</p>
          </div>

          <button onClick={() => this.handleFeedNow()}>Feed Now</button>

          <details ref={this.settingsRef}>
            <summary>Settings</summary>
            <dl>
            {EXPECTED_ACTIONS.map((actionName) => {
                return ( <>
                  <dt key={actionName}>
                    <label>{actionName} </label>
                    <small>{this.state.metadata.actions[actionName].description}</small>
                  </dt>
                  <dd>{this.renderActionInput(actionName, this.state.metadata.actions[actionName])}</dd> </>);
            })}
            </dl>

            <button onClick={() => this.handleSave()}>Save</button>
          </details>

          <details>
            <summary>History</summary>
            <table>
              <thead>
                <tr>
                  <th>Requested</th>
                  <th>Acknowledged</th>
                  <th>Source</th>
                  <th>Portions</th>
                  <th>Weight</th>
                  <th>Requested Size</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {this.state.feedHistory.map((entry, index) => {
                  const timeRequested = entry.time_requested
                    ? new Date(entry.time_requested).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})
                    : '-';
                  const timeAcknowledged = entry.time_acknowledged
                    ? new Date(entry.time_acknowledged).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})
                    : '?';
                  const isError = entry.time_acknowledged === null || entry.error !== null;
                  return (
                    <tr key={index} className={isError ? 'warn' : ''}>
                      <td>{timeRequested}</td>
                      <td>{timeAcknowledged}</td>
                      <td>{entry.source}</td>
                      <td>{entry.portions_dispensed !== null ? entry.portions_dispensed : '-'}</td>
                      <td>{entry.weight_dispensed !== null ? entry.weight_dispensed : '-'}</td>
                      <td>{entry.serving_size_requested !== null ? entry.serving_size_requested : '-'}</td>
                      <td>{entry.error || '-'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </details>

          <details>
            <summary>Schedule</summary>
            <table>
              <thead>
                <tr>
                  <th>Hour</th>
                  <th>Minute</th>
                  <th>Serving Size</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {this.state.editableSchedule.map((entry, index) => (
                  <tr key={index}>
                    <td>{String(entry.hour).padStart(2, '0')}</td>
                    <td>{String(entry.minute).padStart(2, '0')}</td>
                    <td>{entry.serving_size}</td>
                    <td>
                      <button onClick={() => this.handleDeleteScheduleEntry(index)}>Delete</button>
                    </td>
                  </tr>
                ))}
                <tr>
                  <td>
                    <input
                      type="text"
                      value={this.state.newEntryHour}
                      onChange={(e) => this.setState({ newEntryHour: Number(e.target.value) })}
                    />
                  </td>
                  <td>
                    <input
                      type="text"
                      value={this.state.newEntryMinute}
                      onChange={(e) => this.setState({ newEntryMinute: Number(e.target.value) })}
                    />
                  </td>
                  <td>
                    {this.state.metadata.actions.serving_size ? (
                      <>
                        <input
                          type="range"
                          min={this.state.metadata.actions.serving_size.value.meta.value_min}
                          max={this.state.metadata.actions.serving_size.value.meta.value_max}
                          value={this.state.newEntryServingSize}
                          onChange={(e) => this.setState({ newEntryServingSize: Number(e.target.value) })}
                        />
                        <span>{this.state.newEntryServingSize}</span>
                      </>
                    ) : (
                      <input
                        type="number"
                        value={this.state.newEntryServingSize}
                        onChange={(e) => this.setState({ newEntryServingSize: Number(e.target.value) })}
                      />
                    )}
                  </td>
                  <td>
                    <button onClick={() => this.handleAddScheduleEntry()}>Add</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <button onClick={() => this.handleSaveSchedule()}>Save Schedule (will restart service)</button>
          </details>
          </>
        )}
      </section>
    );
  }
}
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
  }

  componentDidUpdate(prevProps) {
    if (prevProps.buttons !== this.props.buttons) {
      this.rebuildGroups();
    }
  }

  on_app_became_visible() {
    this.fetchThings();
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
const INTERESTING_PLOT_METRICS = ['temperature', 'feels_like_temp', 'humidity'];

function buildUrlForPeriod(period, prefix = '/history') {
  if (!period || period == 'all') return '';
  let unit = 'days';
  let time = 1;
  if (period == "hour_1") { unit = "hours"; time = 1; }
  if (period == "hour_6") { unit = "hours"; time = 6; }
  if (period == "hour_12") { unit = "hours"; time = 12; }
  if (period == "day_1") { unit = "days"; time = 1; }
  if (period == "day_2") { unit = "days"; time = 2; }
  return `${prefix}/${unit}/${time}`;
}

// Return sensor data as a list of values
function renderSensorValues(sensorData, metrics) {
  function getUnit(metric) {
    const units = {
      feels_like_temp: '°C',
      temperature: '°C',
      device_temperature: '°C',
      humidity: '%',
      voltage: 'V',
      voltage_volts: 'V',
      battery: '%',
      pm25: 'µg/m³',
      active_power_watts: 'W',
      current_amps: 'A',
      lifetime_energy_use_watt_hour: 'Wh',
      last_minute_energy_use_watt_hour: 'Wh',
    };
    return units[metric] || '';
  }

  function formatValue(value, metric) {
    if (typeof value !== 'number') {
      return '?';
    }
    const unit = getUnit(metric);
    return unit ? `${value}${unit}` : value;
  }

  if (sensorData === undefined) {
    return '...';
  }
  if (sensorData === null) {
    return '?';
  }

  // Check if all values are unknown
  const hasAnyValue = metrics.some(m => typeof sensorData[m] === 'number');
  if (!hasAnyValue) {
    return 'No data yet';
  }

  if (metrics.length === 1) {
    // Single metric: just show the value
    return formatValue(sensorData[metrics[0]], metrics[0]);
  } else {
    // Multiple metrics: show key=value pairs
    return metrics
      .map(m => `${m}=${formatValue(sensorData[m], m)}`)
      .join(', ');
  }
}


function simple_dygraph_plot(html_elm_id, url) {
  let dygraph_opts = {
                      fillGraph: false,
                      connectSeparatedPoints: true,
                      highlightCircleSize: 2,
                      strokeWidth: 1,
                      width: window.innerWidth * .9,
                      // smooth graph, helps fill in periods where sensors aren't concurrent
                      rollPeriod: 5,
                      legend: 'always',
                      highlightSeriesOpts: {
                          strokeWidth: 3,
                          strokeBorderWidth: 1,
                          highlightCircleSize: 5
                      },
                  };

  mTextGet(url, (t_csv) => {
    const label_elm = document.getElementById(html_elm_id + '_label');
    if (label_elm) {
      dygraph_opts['labelsDiv'] = label_elm;
    }
    new Dygraph(
        document.getElementById(html_elm_id),
        t_csv,
        dygraph_opts);
  });
}

class SensorsHistoryPane extends React.Component {
  static buildProps() {
    const urlParams = new URLSearchParams(window.location.search);
    const urlQueryMetric = urlParams.get('metric');
    const metric = urlQueryMetric ? [urlQueryMetric] : INTERESTING_PLOT_METRICS;
    const urlQueryPeriod = urlParams.get('period');
    const period = urlQueryPeriod ? [urlQueryPeriod] : 'day_2';
    const plotSingleMetric = !!urlQueryMetric;
    const selectedSensor = urlParams.get('sensor');

    return {
      plotSingleMetric,
      metrics_to_plot: metric,
      period,
      selectedSensor,
      key: 'SensorsHistoryPane',
    };
  }

  constructor(props) {
    super(props);
    this.loadPlotsForSensorMeasuring = this.loadPlotsForSensorMeasuring.bind(this);
    this.updateConfigPeriod = this.updateConfigPeriod.bind(this);
    this.updateConfigMetric = this.updateConfigMetric.bind(this);
    this.sensorsListRef = React.createRef();

    this.state = {
      sensors: null,
      period: this.props.period,
      allMetrics: [],
      selectedMetrics: this.props.metrics_to_plot,
      selectedSensor: this.props.selectedSensor,
      sensorMetrics: null,
    };
  }

  componentDidMount() {
    this.on_app_became_visible();
  }

  on_app_became_visible() {
    mJsonGet('/sensors/metrics', metrics => {
        this.setState({
          allMetrics: metrics,
          sensors: null // Force reload of plots
        });
    });
    if (this.sensorsListRef.current) {
      this.sensorsListRef.current.loadSensors();
    }
  }

  updateConfigPeriod() {
    const period = document.getElementById('SensorsHistoryConfig_period').value;
    window.history.replaceState(null, "Sensors", `?metric=${this.state.selectedMetrics.join(',')}&period=${period}`);
    this.setState({ period });
  }

  updateConfigMetric() {
    const select = document.getElementById('SensorsHistoryConfig_metric');
    const selected = Array.from(select.selectedOptions).map(o => o.value);

    window.history.replaceState(
      null,
      "Sensors",
      `?metric=${selected.join(',')}&period=${this.state.period}`
    );

    this.setState({
      selectedMetrics: selected,
      sensors: null, // reset so plots reload
    });
  }

  render() {
    return (
      <div id="SensorsHistoryPane">
        <div class="SensorsHistoryConfig">
          <label htmlFor="SensorsHistoryConfig_period">Period:</label>
          <select
            value={this.state.period}
            name="SensorsHistoryConfig_period"
            id="SensorsHistoryConfig_period"
            onChange={this.updateConfigPeriod}
          >
            <option value="hour_1">Last hour</option>
            <option value="hour_6">Last 6 hours</option>
            <option value="hour_12">Last 12 hours</option>
            <option value="day_1">Last day</option>
            <option value="day_2">Last 2 days</option>
            <option value="all">All</option>
          </select>

          <label htmlFor="SensorsHistoryConfig_metric" style={{ marginLeft: "10px" }}>
            Metrics:
          </label>
          <select
            id="SensorsHistoryConfig_metric"
            multiple
            value={this.state.selectedMetrics}
            onChange={this.updateConfigMetric}
          >
            {this.state.allMetrics.map(m => (
              <option value={m} key={m}>{m}</option>
            ))}
          </select>
        </div>

        <SensorsList ref={this.sensorsListRef} metrics={this.state.selectedMetrics} api_base_path={this.props.api_base_path} />

        {this.render_plots()}
      </div>
    );
  }

  render_plots() {
    // Single sensor view: show all metrics for one sensor
    if (this.state.selectedSensor) {
      if (!this.state.sensorMetrics) {
        this.loadMetricsForSensor(this.state.selectedSensor);
        return "Loading sensor metrics...";
      }
      return this.renderSingleSensor(this.state.selectedSensor, this.state.sensorMetrics);
    }

    // Metric-based views
    const metrics = this.state.selectedMetrics;

    if (metrics.length === 1 && !this.state.sensors) {
      this.loadPlotsForSensorMeasuring(metrics[0]);
      return "Loading sensors...";
    } else if (metrics.length === 1) {
      return this.renderSingleMetric(metrics[0], this.state.sensors);
    } else {
      return this.renderMetricInAllSensors(metrics);
    }
  }

  loadMetricsForSensor(sensorName) {
    mJsonGet(`/sensors/metrics/${sensorName}`,
      (metrics) => { this.setState({ sensorMetrics: metrics }); });
  }

  renderSingleSensor(sensorName, metrics) {
    let local_plots = [];
    for (const metric of metrics) {
      const plotId = `local_plot_${sensorName}_${metric}`;
      const url = `/sensors/get_metric_in_sensor_csv/${sensorName}/${metric}${buildUrlForPeriod(this.state.period)}`;

      setTimeout(() => {
        const plotDiv = document.getElementById(plotId);
        if (plotDiv) {
          plotDiv.innerHTML = '';
        }
        simple_dygraph_plot(plotId, url);
      }, 50);

      local_plots.push(
        <div className="card" key={`${sensorName}_${metric}_${this.state.period}_div`}>
          <h3><a href={`?metric=${metric}`}>{metric}</a> for {sensorName}</h3>
          <div id={plotId} />
          <div id={`${plotId}_label`} />
        </div>
      );
    }

    return local_plots;
  }

  renderMetricInAllSensors(metrics) {
    let local_plots = [];
    for (const metric of metrics) {
      const plotId = `local_plot_${metric}`;
      const url = `/sensors/get_single_metric_in_all_sensors_csv/${metric}${buildUrlForPeriod(this.state.period, '')}`;

      // Clear existing plot div content to force recreation
      setTimeout(() => {
        const plotDiv = document.getElementById(plotId);
        if (plotDiv) {
          plotDiv.innerHTML = '';
        }
        simple_dygraph_plot(plotId, url);
      }, 0);

      local_plots.push(
        <div className="card" key={`${metric}_${this.state.period}_div`}>
          <h3><a href={`?metric=${metric}`}>{metric}</a></h3>
          <div id={plotId} />
          <div id={`${plotId}_label`} />
        </div>
      );
    }

    return local_plots;
  }

  loadPlotsForSensorMeasuring(metric) {
    mJsonGet(`/sensors/measuring/${metric}`,
      (sensors) => { this.setState({ sensors }); });
  }

  renderSingleMetric(metric, sensors) {
    let local_plots = [];
    for (const sensor of sensors) {
      const plotId = `local_plot_${sensor}`;
      const url = `/sensors/get_metric_in_sensor_csv/${sensor}/${metric}${buildUrlForPeriod(this.state.period)}`;

      // Clear existing plot div content to force recreation
      setTimeout(() => {
        const plotDiv = document.getElementById(plotId);
        if (plotDiv) {
          plotDiv.innerHTML = '';
        }
        simple_dygraph_plot(plotId, url);
      }, 50); // Give it a bit of time to let the element load, otherwise Dygraph can't find it

      local_plots.push(
        <div className="card" key={`${sensor}_${this.state.period}_div`}>
          <h3>{metric} for {sensor}</h3>
          <div id={plotId} />
          <div id={`${plotId}_label`} />
        </div>
      );
    }

    return local_plots;
  }
};

class SensorsList extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      sensors: null,
      sensorData: {},
    };
  }

  componentDidMount() {
    this.loadSensors();
  }

  componentDidUpdate(prevProps) {
    if (prevProps.metrics !== this.props.metrics) {
      this.loadSensors();
    }
  }

  loadSensors() {
    const metrics = this.props.metrics;
    if (!metrics || metrics.length === 0) {
      this.setState({ sensors: [], sensorData: {} });
      return;
    }

    const basePath = this.props.api_base_path || '';

    // Fetch all metrics in parallel using the combined endpoint
    const allSensorData = {};
    let pending = metrics.length;

    metrics.forEach(metric => {
      mJsonGet(`${basePath}/sensors/get_all/${metric}`, data => {
        // data is {"SensorA": value, "SensorB": value, ...}
        for (const [sensor, value] of Object.entries(data)) {
          if (!allSensorData[sensor]) {
            allSensorData[sensor] = {};
          }
          allSensorData[sensor][metric] = value;
        }
        pending--;
        if (pending === 0) {
          const sensors = Object.keys(allSensorData).sort();
          this.setState({ sensors, sensorData: allSensorData });
        }
      });
    });
  }

  render() {
    if (this.state.sensors === null) {
      return (<div className="card hint">
              <p>Loading sensors!</p>
              <p>Please wait...</p>
              </div>)
    }

    return (
      <ul className="not-a-list">
        {this.state.sensors.map(sensor => (
          <li key={sensor} className="infobadge">
            <a href={`?sensor=${sensor}`}>{sensor}</a>: {renderSensorValues(this.state.sensorData[sensor], this.props.metrics)}
          </li>
        ))}
      </ul>
    );
  }
}
function getMediaType(speaker) {
  if (speaker.is_playing_line_in) return 'Line-In';
  if (speaker.is_playing_radio) return 'Radio';
  if (speaker.is_playing_tv) return 'TV';
  if (speaker.transport_state === 'PLAYING') return 'Other';
  return null;
}

function findSpeakerGroup(speakerName, groups) {
  for (const [coordinator, members] of Object.entries(groups)) {
    if (members.includes(speakerName)) {
      return coordinator;
    }
  }
  return null;
}

class SonosSpeaker extends React.Component {
  onVolumeChange(e) {
    const v = parseInt(e.target.value, 10);
    this.props.onVolumeChange(this.props.speaker.name, v);
  }

  renderExtraCfgs() {
    const speaker = this.props.speaker;
    const speakerInfo = speaker.speaker_info || {};
    const mediaType = getMediaType(speaker);

    return (
      <details className="light_details">
        <summary>⚙</summary>
        <div>
          <div>Name: {speakerInfo.player_name || speaker.name}</div>
          <div>Model: {speakerInfo.model_name}</div>
          <div>Model Number: {speakerInfo.model_number}</div>
          <div>Zone: {speakerInfo.zone_name}</div>
          <div>URI: {speaker.uri || 'None'}</div>
          <div>Media Type: {mediaType || 'None'}</div>
        </div>
      </details>
    );
  }

  render() {
    const speaker = this.props.speaker;
    const groups = this.props.groups;
    const groupCoordinator = findSpeakerGroup(speaker.name, groups);
    let transport = speaker.transport_state;
    if (speaker.transport_state === "PLAYING") transport = '▶';
    if (speaker.transport_state === "PAUSED_PLAYBACK") transport = '⏸';
    if (speaker.transport_state === "STOPPED") transport = 'Stopped';
    if (groupCoordinator && groupCoordinator != speaker.name) transport = `Follows ${groupCoordinator}`;
    return (
      <li>
        <p>
          <input
            id={`${speaker.name}_control`}
            type="checkbox"
            checked={this.props.controlSelected}
            onChange={() => this.props.onControlToggle(speaker.name)}
          />
          <label htmlFor={`${speaker.name}_control`}>{speaker.name}</label> [{transport}]
        </p>
        Vol: {this.props.volume}
        <DebouncedRange
          min={0}
          max={100}
          value={this.props.volume}
          onChange={(e) => this.onVolumeChange(e)}
        />
        {this.renderExtraCfgs()}
      </li>
    );
  }
}

class SonosCtrl extends React.Component {
  static buildProps(api_base_path = '', baseServer = '') {
    return {
      key: 'SonosCtrl',
      api_base_path: api_base_path,
      baseServer: baseServer,
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      speakers: null,
      groups: null,
      zones: null,
      controlSpeakers: {},
      masterVolume: 50,
      spotifyContext: null,
      speakerVolumes: {},
      volumeRatios: {},
      wsInProgress: false,
      wsLogs: [],
      wsComplete: false,
    };
  }

  onControlToggle(speakerName) {
    this.setState(prev => ({
      controlSpeakers: {
        ...prev.controlSpeakers,
        [speakerName]: !prev.controlSpeakers[speakerName],
      },
    }));
  }

  startWebSocketAction(endpoint, initialMsg, payload) {
    this.setState({
      wsInProgress: true,
      wsLogs: [initialMsg],
      wsComplete: false,
    });

    let wsUrl;
    if (this.props.baseServer) {
      const wsHost = this.props.baseServer.replace(/^https?:\/\//, '');
      const protocol = this.props.baseServer.startsWith('https:') ? 'wss:' : 'ws:';
      wsUrl = `${protocol}//${wsHost}${endpoint}`;
    } else {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      wsUrl = `${protocol}//${window.location.host}${this.props.api_base_path}${endpoint}`;
    }
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      ws.send(JSON.stringify(payload));
    };

    ws.onmessage = (event) => {
      this.setState(prev => ({
        wsLogs: [...prev.wsLogs, event.data],
      }));
    };

    ws.onclose = () => {
      this.setState({ wsInProgress: false, wsComplete: true });
    };

    ws.onerror = () => {
      this.setState({ wsInProgress: false, wsComplete: true });
    };
  }

  getSelectedSpeakers() {
    const { controlSpeakers, speakerVolumes } = this.state;
    const speakers = {};
    const speakerNames = [];
    for (const [name, selected] of Object.entries(controlSpeakers)) {
      if (selected) {
        speakers[name] = { vol: speakerVolumes[name] || 0 };
        speakerNames.push(name);
      }
    }
    return { speakers, speakerNames };
  }

  onSpotifyHijack() {
    const { speakers, speakerNames } = this.getSelectedSpeakers();
    if (Object.keys(speakers).length === 0) {
      showGlobalError("You need to select a set of speakers to control");
      return;
    }
    this.startWebSocketAction('/spotify_hijack', `Requested Spotify-Hijack to ${speakerNames.join(', ')}`, speakers);
  }

  onLineInRequested() {
    const { speakers, speakerNames } = this.getSelectedSpeakers();
    if (Object.keys(speakers).length === 0) {
      showGlobalError("You need to select a set of speakers to control");
      return;
    }
    this.startWebSocketAction('/line_in_requested', `Requested Line-In to ${speakerNames.join(', ')}`, speakers);
  }

  onWsLogClose() {
    this.setState({ wsLogs: [], wsComplete: false });
  }

  onStopAll() { mJsonPut(`${this.props.api_base_path}/stop_all_playback`); }
  onPrevTrackRq() { mJsonPut(`${this.props.api_base_path}/prev_track`); }
  onNextTrackRq() { mJsonPut(`${this.props.api_base_path}/next_track`); }

  onSpeakerVolumeChange(speakerName, volume) {
    this.setState(prev => {
      // Update ratio = master / speaker
      const newRatio = volume > 0 ? prev.masterVolume / volume : prev.masterVolume;
      return {
        speakerVolumes: {
          ...prev.speakerVolumes,
          [speakerName]: volume,
        },
        volumeRatios: {
          ...prev.volumeRatios,
          [speakerName]: newRatio,
        },
      };
    });
    mJsonPut(`${this.props.api_base_path}/volume`, { [speakerName]: volume });
  }

  onMasterVolumeChange(e) {
    const newMaster = parseInt(e.target.value, 10);
    const { volumeRatios, controlSpeakers, speakerVolumes } = this.state;

    // Calculate new volumes only for controlled speakers
    const updatedVolumes = {};
    for (const [name, ratio] of Object.entries(volumeRatios)) {
      if (controlSpeakers[name]) {
        const newVol = Math.round(Math.min(100, Math.max(0, newMaster / ratio)));
        updatedVolumes[name] = newVol;
      }
    }

    if (Object.keys(updatedVolumes).length > 0) {
      mJsonPut(`${this.props.api_base_path}/volume`, updatedVolumes);
    }

    this.setState({
      masterVolume: newMaster,
      speakerVolumes: { ...speakerVolumes, ...updatedVolumes },
    });
  }

  componentDidMount() {
    this.fetchState();
  }

  on_app_became_visible() {
    this.fetchState();
  }

  fetchState() {
    mJsonGet(`${this.props.api_base_path}/world_state`, (data) => {
      const speakerVolumes = {};
      const volumeRatios = {};
      const masterVolume = this.state.masterVolume;
      for (const speaker of data.speakers) {
        speakerVolumes[speaker.name] = speaker.volume;
        // ratio = master / speaker, avoid division by zero
        volumeRatios[speaker.name] = speaker.volume > 0 ? masterVolume / speaker.volume : masterVolume;
      }
      this.setState({
        speakers: data.speakers,
        groups: data.groups,
        zones: data.zones,
        speakerVolumes: speakerVolumes,
        volumeRatios: volumeRatios,
      });
    });
    mJsonGet(`${this.props.api_base_path}/get_spotify_context`, (data) => {
      this.setState({ spotifyContext: data });
    });
  }

  render() {
    if (!this.state.speakers) {
      return <div>Loading...</div>;
    }

    const spotifyUri = this.state.spotifyContext?.media_info?.context?.uri;
    const hasSpotify = spotifyUri != null;

    return (
      <div id="zmw_lights">
        <div id="master_ctrls" className="card">
          <button onClick={() => this.fetchState()}>↻</button>
          <button
            onClick={() => this.onSpotifyHijack()}
            disabled={!hasSpotify || this.state.wsInProgress}
          >
            {this.state.wsInProgress ? 'Working...' : (hasSpotify ? 'Spotify Hijack' : 'Spotify Hijack (Not playing)')}
          </button>
          <button
            onClick={() => this.onLineInRequested()}
            disabled={this.state.wsInProgress}
          >
            Line in
          </button>
          <button onClick={() => this.onStopAll()}>Stop all</button>
          <button onClick={() => this.onPrevTrackRq()}>Prev</button>
          <button onClick={() => this.onNextTrackRq()}>Next</button>
          { /*<div>URI: {this.state.spotifyUri || 'None'}</div>*/ } 

          <label>Master volume</label>
          <DebouncedRange
            min={0}
            max={100}
            value={this.state.masterVolume}
            onChange={(e) => this.onMasterVolumeChange(e)}
          />
        </div>
        {this.state.wsLogs.length > 0 && (
          <div id="ws_log">
            <pre>{this.state.wsLogs.join('\n')}</pre>
            {this.state.wsComplete && (
              <button onClick={() => this.onWsLogClose()}>Close</button>
            )}
          </div>
        )}
        <details open>
          <summary>Speakers</summary>
          <ul>
            {this.state.speakers.map((speaker) => (
              <SonosSpeaker
                key={speaker.name}
                speaker={speaker}
                groups={this.state.groups}
                api_base_path={this.props.api_base_path}
                controlSelected={!!this.state.controlSpeakers[speaker.name]}
                onControlToggle={(name) => this.onControlToggle(name)}
                volume={this.state.speakerVolumes[speaker.name] || 0}
                onVolumeChange={(name, vol) => this.onSpeakerVolumeChange(name, vol)}
              />
            ))}
          </ul>
        </details>
      </div>
    );
  }
}
class TTSAnnounce extends React.Component {
  static buildProps(api_base_path = '', https_server = '') {
    return {
      key: 'tts_announce',
      api_base_path,
      https_server,
    };
  }

  constructor(props) {
    super(props);
    this.canRecordMic = window.location.protocol === "https:";

    this.state = {
      ttsPhrase: "",
      ttsLang: "es-ES",
      ttsVolume: 50,
      isRecording: false,
      speakerList: null,
      announcementHistory: [],
      historyExpanded: false,
      httpsServer: null,
    };

    this.recorderRef = React.createRef();
    this.onTTSRequested = this.onTTSRequested.bind(this);
    this.onMicRecRequested = this.onMicRecRequested.bind(this);
    this.onMicRecSend = this.onMicRecSend.bind(this);
    this.onCancel = this.onCancel.bind(this);
    this.fetchAnnouncementHistory = this.fetchAnnouncementHistory.bind(this);
  }

  componentDidMount() {
    this.on_app_became_visible();
  }

  on_app_became_visible() {
    mJsonGet(`${this.props.api_base_path}/ls_speakers`, (data) => this.setState({ speakerList: data }));
    mJsonGet(`${this.props.api_base_path}/svc_config`, (data) => this.setState({ httpsServer: data.https_server }));
    this.fetchAnnouncementHistory();
  }

  fetchAnnouncementHistory() {
    mJsonGet(`${this.props.api_base_path}/announcement_history`, (data) => this.setState({ announcementHistory: data }));
  }

  onTTSRequested() {
    const phrase = this.state.ttsPhrase.trim() || prompt("What is so important?");
    if (!phrase) return;
    this.setState({ ttsPhrase: phrase });

    console.log(`announce {"lang": "${this.state.ttsLang}", "phrase": "${phrase}"}`);

    const newEntry = {
      timestamp: new Date().toISOString(),
      phrase: phrase,
      lang: this.state.ttsLang,
      volume: this.state.ttsVolume,
      uri: `${this.props.api_base_path}/tts/${phrase}_${this.state.ttsLang}.mp3`
    };

    this.setState(prev => ({
      announcementHistory: [...prev.announcementHistory, newEntry].slice(-10)
    }));

    console.log(`${this.props.api_base_path}/announce_tts?lang=${this.state.ttsLang}&phrase=${phrase}&vol=${this.state.ttsVolume}`)
    mJsonGet(
      `${this.props.api_base_path}/announce_tts?lang=${this.state.ttsLang}&phrase=${phrase}&vol=${this.state.ttsVolume}`,
      () => {
        console.log("Sent TTS request");
        this.setState({ ttsPhrase: "" });
        this.fetchAnnouncementHistory();
      });
  }

  async onMicRecRequested() {
    if (!this.canRecordMic) {
      showGlobalError("Mic recording only works on https pages");
      return;
    }

    if (!navigator.mediaDevices) {
      showGlobalError("Your browser does not support microphone recording");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      const rec = new MediaRecorder(stream);

      rec.chunks = [];
      rec.ondataavailable = e => rec.chunks.push(e.data);

      this.recorderRef.current = rec;
      rec.start();
      this.setState({ isRecording: true });
    } catch (err) {
      showGlobalError("Mic error: " + err);
    }
  }

  onMicRecSend() {
    const rec = this.recorderRef.current;
    if (!rec) {
      showGlobalError("No microphone recording in progress");
      return;
    }

    rec.onstop = () => {
      const blob = new Blob(rec.chunks, { type: "audio/ogg; codecs=opus" });

      const form = new FormData();
      form.append("audio_data", blob, "mic_cap.ogg");
      form.append("vol", this.state.ttsVolume);

      fetch(`${this.props.api_base_path}/announce_user_recording`, {
        method: 'POST',
        body: form
      }).then(resp => {
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          console.log("Sent user recording");
      })
      .catch(showGlobalError);

      rec.stream.getTracks().forEach(t => t.stop());
      this.recorderRef.current = null;
      this.setState({ isRecording: false });
    };

    rec.stop();
  }

  onCancel() {
    const rec = this.recorderRef.current;
    if (rec) {
      rec.stream.getTracks().forEach(t => t.stop());
      this.recorderRef.current = null;
    }
    this.setState({ isRecording: false });
  }

  render() {
    return (
      <div>
        <input
          type="text"
          placeholder="Text to announce"
          value={this.state.ttsPhrase}
          onChange={e => this.setState({ ttsPhrase: e.target.value })}
        />

        <div className="ctrl-box-with-range">
          <button onClick={this.onTTSRequested}>
            Announce!
          </button>

          <select
            value={this.state.ttsLang}
            onChange={e => this.setState({ ttsLang: e.target.value })}>
            { /* https://developers.google.com/assistant/console/languages-locales */ }
            <option value="es-ES">ES</option>
            <option value="es-419">es 419</option>
            <option value="en-GB">EN GB</option>
          </select>

          {!this.canRecordMic ? (
              this.state.httpsServer ? (
                <button onClick={() => window.location.href = this.state.httpsServer}>
                  OpenRecorder
                </button>
              ) : (
                <button disabled>Record</button>
              )
          ) : (
            this.state.isRecording ? (
              <>
              <div className="card warn" style={{flex: "0 0 25%"}}>
                <p>Recording in progress!</p>
                <button onClick={this.onMicRecSend}>Send</button>
                <button onClick={this.onCancel}>Cancel</button>
              </div>
              </>
            ) : (
              <button onClick={this.onMicRecRequested}>Record</button>
            )
          )}

          <label>Vol</label>
          <input
            type="range"
            min="0"
            max="100"
            value={this.state.ttsVolume}
            onChange={e => this.setState({ ttsVolume: parseInt(e.target.value, 10) })}
            title={`Volume: ${this.state.ttsVolume}%`}
          />
        </div>

        {this.state.speakerList && (
          <small>
            Will announce in: <ul className="compact-list">
              {this.state.speakerList.map(x => <li key={x}>{x}</li>) }
            </ul>
          </small>
        )}

        <details className="light_details">
          <summary><small>Announcement History ({this.state.announcementHistory.length})</small></summary>
          {this.state.announcementHistory.length === 0 ? (
            <p>No announcements yet</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Phrase</th>
                  <th>Lang</th>
                  <th>Vol</th>
                  <th>Link</th>
                </tr>
              </thead>
              <tbody>
                {this.state.announcementHistory.slice().reverse().map((item, idx) => (
                  <tr key={idx}>
                    <td>{new Date(item.timestamp).toLocaleString()}</td>
                    <td>{item.phrase}</td>
                    <td>{item.lang || "default"}</td>
                    <td>{item.volume}</td>
                    <td><a href={item.uri}>🔊</a></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </details>
      </div>
    );
  }
}
const ProxiedServices = {
  CACHE_KEY: 'proxied_services',
  _services: null,
  _storage: new LocalStorageManager(),

  _fetchServices(callback) {
    mJsonGet('/get_proxied_services', services => {
      this._services = services;
      this._storage.cacheSave(this.CACHE_KEY, services);
      if (callback) callback(services);
    });
  },

  get(serviceName) {
    return this._services ? this._services[serviceName] : null;
  },

  init(callback) {
    const fresh = this._storage.cacheGet(this.CACHE_KEY);
    const cached = fresh || this._storage.cacheGet_ignoreExpire(this.CACHE_KEY);

    if (cached) {
      this._services = cached;
      if (!fresh) this._fetchServices(); // Refresh in background if expired
      callback();
    } else {
      this._fetchServices(callback);
    }
  },
};

class AlertsList extends React.Component {
  constructor(props) {
    super(props);
    this.state = { alerts: [] };
  }

  componentDidMount() {
    this.fetchAlerts();
    this.interval = setInterval(() => this.fetchAlerts(), 30000);
  }

  componentWillUnmount() {
    if (this.interval) clearInterval(this.interval);
  }

  fetchAlerts() {
    mJsonGet('/svc_alerts', (res) => {
      this.setState({ alerts: res || [] });
    });
  }

  render() {
    if (this.state.alerts.length === 0) {
      return null;
    }
    return (
      <div className="card warn">
        <p>Alert!</p>
        <ul>
          {this.state.alerts.map((alert, idx) => (
            <li key={idx}>{alert}</li>
          ))}
        </ul>
      </div>
    );
  }
}

/* The scenes service is exposed by a user service, so we don't depend directly on the user app. Instead
 * we depend on a couple of endpoints like /ls_scenes to retrieve the right content. */
class ScenesList extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      scenes: [],
      sceneStatus: null,
    };
    this.fetchScenes = this.fetchScenes.bind(this);
    this.applyScene = this.applyScene.bind(this);
  }

  componentDidMount() {
    this.fetchScenes();
  }

  fetchScenes() {
    mJsonGet(this.props.api_base_path + '/ls_scenes', (res) => {
      this.setState({ scenes: res || [] });
    });
  }

  applyScene(scene) {
    mJsonGet(this.props.api_base_path + '/apply_scene?scene=' + encodeURIComponent(scene), (res) => {
      if (res && res.success) {
        this.setState({ sceneStatus: 'Scene applied' });
        setTimeout(() => {
          this.setState({ sceneStatus: null });
        }, 3000);
      }
    });
  }

  render() {
    if (this.state.scenes.length === 0) {
      return null;
    }

    return (
        <ul className="not-a-list">
          {this.state.scenes.map((scene, idx) => (
            <li key={idx}>
              <button type="button" onClick={() => this.applyScene(scene)}>{scene.replace(/_/g, ' ')}</button>
            </li>
          ))}
          {this.state.sceneStatus && 
            <li><blockquote className="hint">{this.state.sceneStatus}</blockquote></li>}
        </ul>
    );
  }
}


class LightsSection extends React.Component {
  constructor(props) {
    super(props);
    this.state = { scenes: [] };
  }

  componentDidMount() {
    mJsonGet('/Scenes/ls_scenes', (scenes) => {
      if (!scenes || !Array.isArray(scenes)) {
        showGlobalError("Scenes API isn't working");
        return;
      }

      // Convert scenes to button format: [{"SceneName": "url"}, ...]
      const buttons = scenes.map(scene => ({
        [scene]: `/Scenes/apply_scene?scene=${encodeURIComponent(scene)}`
      }));
      this.setState({ scenes: buttons });
    });
  }

  render() {
    return (
      <section id="lights-section">
        <a className="section-badge" href={ProxiedServices.get('ZmwLights')}><img src="/ZmwLights/favicon.ico"/></a>
        {React.createElement(
          MqttLights,
          MqttLights.buildProps('/ZmwLights', this.state.scenes))}
      </section>
    );
  }
}

function SensorsListSection(props) {
  return (
    <section id="sensors-list-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwSensormon')}><img src="/ZmwSensormon/favicon.ico"/></a>
      {React.createElement(
        SensorsList,
        { metrics: ['temperature'], api_base_path: '/ZmwSensormon' })}
    </section>
  );
}

function CatSection(props) {
  return (
    <section id="catsnacks-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwCatSnackDispenser')}><img src="/ZmwCatSnackDispenser/favicon.ico"/></a>
      {React.createElement(
        CatFeeder,
        CatFeeder.buildProps('/ZmwCatSnackDispenser'))}
    </section>
  );
}

function TTSAnnounceSection(props) {
  return (
    <section id="ttsannounce-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwSpeakerAnnounce')}><img src="/ZmwSpeakerAnnounce/favicon.ico"/></a>
      {React.createElement(
        TTSAnnounce,
        TTSAnnounce.buildProps('/ZmwSpeakerAnnounce'))}
    </section>
  );
}

function DoormanSection(props) {
  return (
    <section id="doorman-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwDoorman')}><img src="/ZmwDoorman/favicon.ico"/></a>
      {React.createElement(
        DoorMan,
        DoorMan.buildProps('/ZmwDoorman'))}
    </section>
  );
}

function MqttHeatingSection(props) {
  return (
    <section id="heating-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwHeating')}><img src="/ZmwHeating/favicon.ico"/></a>
      {React.createElement(
        HeatingControls,
        HeatingControls.buildProps('/ZmwHeating'))}
    </section>
  );
}

function SonosCtrlSection(props) {
  return (
    <section id="sonos-ctrl-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwSonosCtrl')}><img src="/ZmwSonosCtrl/favicon.ico"/></a>
      {React.createElement(
        SonosCtrl,
        SonosCtrl.buildProps('/ZmwSonosCtrl', ProxiedServices.get('ZmwSonosCtrl')))}
    </section>
  );
}

function ConfigSection(props) {
  const store = React.useMemo(() => new LocalStorageManager(), []);
  const savedTheme = store.cacheGet("ZmwDashboardConfig")?.theme || "no-theme";
  const [userLinks, setUserLinks] = React.useState([]);

  React.useEffect(() => {
    mJsonGet('/get_user_defined_links', (links) => {
      setUserLinks(links || []);
    });
  }, []);

  const handleThemeChange = (e) => {
    const theme = e.target.value;
    document.documentElement.setAttribute('data-theme', theme);
    store.cacheSave("ZmwDashboardConfig", { theme });
  };

  const handleClearCache = () => {
    localStorage.clear();
    location.reload();
  };

  return (
    <section id="config-section">
      <img className="section-badge" src="/settings.ico"/>
      <div style={{display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '0.5rem', alignItems: 'center'}}>
        <label>Fix things:</label>
        <div><button alt="This fixes things if something is out of sync" onClick={handleClearCache}>Clear cache</button></div>

        <label htmlFor="configTheme">Theme:</label>
        <div>
          <select id="configTheme" defaultValue={savedTheme} onChange={handleThemeChange}>
            <option value="no-theme">no theme</option>
            <option value="dark">dark</option>
            <option value="light">light</option>
            <option value="sepia">sepia</option>
            <option value="milligram">milligram</option>
            <option value="pure">pure</option>
            <option value="sakura">sakura</option>
            <option value="skeleton">skeleton</option>
            <option value="bootstrap">bootstrap</option>
            <option value="medium">medium</option>
            <option value="tufte">tufte</option>
          </select>
        </div>

        <label>More services:</label>
        <div>
          {userLinks.map((link, idx) => (
            <button key={idx} onClick={() => window.open(link.url, '_blank')}>
              <img src={link.icon} alt=""/>
              {link.label}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}


// Main Dashboard Component
function Dashboard(props) {
  const [expandedSection, setExpandedSection] = React.useState(null);
  const contentRef = React.useRef(null);

  const toggleSection = (section) => {
    const newSection = expandedSection === section ? null : section;
    setExpandedSection(newSection);

    // Scroll to content after state update
    if (newSection !== null) {
      setTimeout(() => {
        if (contentRef.current) {
          contentRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }, 50);
    }
  };

  const renderIcoBtn = (sectionName, icoUrl) => {
    return <button
              data-selected={expandedSection === sectionName}
              onClick={() => toggleSection(sectionName)}
           >
              <img src={icoUrl} alt=""/>
              {sectionName}
           </button>
  }
  const renderSvcBtn =
    (sectionName, serviceName) => renderIcoBtn(sectionName, `/${serviceName}/favicon.ico`);

  return (
    <main>
      <AlertsList />
      <LightsSection />
      <SensorsListSection />

      <section id="zmw_other_services">
        { renderSvcBtn('Shout', 'ZmwSpeakerAnnounce') }
        { renderSvcBtn('Cat', 'ZmwCatSnackDispenser') }
        { renderSvcBtn('Door', 'ZmwDoorman') }
        { renderSvcBtn('Heat', 'ZmwHeating') }
        { renderSvcBtn('Sonos', 'ZmwSonosCtrl') }
        { renderIcoBtn('⚙', '/settings.ico') }
      </section>

      <div ref={contentRef}>
        {expandedSection === 'Shout' && <TTSAnnounceSection />}
        {expandedSection === 'Cat' && <CatSection />}
        {expandedSection === 'Door' && <DoormanSection />}
        {expandedSection === 'Heat' && <MqttHeatingSection />}
        {expandedSection === 'Sonos' && <SonosCtrlSection />}
        {expandedSection === '⚙' && <ConfigSection />}
      </div>
    </main>
  );
}

Dashboard.buildProps = () => ({ key: 'dashboard' });

// Initialize: fetch prefetch data and start React app in parallel
const store = new LocalStorageManager();
const opts = store.cacheGet("ZmwDashboardConfig", null);
document.documentElement.setAttribute('data-theme', opts?.theme);

ProxiedServices.init(() => {}); // Fetch in background for badge links
z2mStartReactApp('#app_root', Dashboard);
