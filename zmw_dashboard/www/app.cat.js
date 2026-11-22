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
    mFetch(`${this.props.api_base_path}/request_snap`, { method: 'PUT' });
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

  // The visitor detection UI opens the session named in its URL's #session=<id>
  openVisitorSession(sessionId) {
    mJsonGet(`${this.props.api_base_path}/get_visitor_detect_svc_url`, (res) => {
      if (res.url) {
        window.open(`${res.url.replace(/\/$/, '')}/index.html#session=${encodeURIComponent(sessionId)}`, '_blank');
      } else {
        showGlobalError("Visitor detection service has no known URL");
      }
    });
  }

  renderHistoryDetail(e) {
    if (e.event_type === 'visitor') {
      if (!e.session_id) return e.msg;
      return <a href="#" onClick={(ev) => { ev.preventDefault(); this.openVisitorSession(e.session_id); }}>{e.msg}</a>;
    }
    return e.snap ? <a href={`${this.props.api_base_path}/get_snap/${e.snap}`} target="_blank">{e.snap}</a> : '-';
  }

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
    mFetch(`${this.props.api_base_path}/skip_chimes`, { method: 'PUT' })
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
          <tr><th>Type</th><th>Time</th><th>Duration</th><th>Snap / visitor</th></tr>
        </thead>
        <tbody>
          {history.map((e, i) => (
            <tr key={i}>
              <td>{e.event_type}</td>
              <td>{this.formatTimestamp(e.time)}</td>
              <td>{e.duration_secs !== undefined ? this.formatDuration(e.duration_secs) : '-'}</td>
              <td>{this.renderHistoryDetail(e)}</td>
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
          <p>Today: Doorbell rang {stats.doorbell_press_count_today} times, {stats.motion_detection_count_today} motion events,
             {' '}{stats.visitor_count_today || 0} visitors notified.
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
    // If no data provided via props, fetch it (and keep it fresh, same as MqttHeating). Otherwise the parent owns
    // the data and its refreshing.
    if (!this.props.allow_on && this.props.api_base_path) {
      this._refresh();
      this._poller = mPoll(this._refresh, 30000);
    }
  }

  componentWillUnmount() {
    this._poller?.stop();
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
    this._poll = this._poll.bind(this);
    this._poller = null;

    this.state = {
      configuring: false,
      active_schedule: null,
      schedule_template: null,
      allow_on: null,
      mqtt_thing_reports_on: null,
      monitoring_sensors: null,
    };
  }

  componentDidMount() {
    this._poller = mPoll(this._poll, 30000);
  }

  componentWillUnmount() {
    this._poller?.stop();
  }

  _poll() {
    // Refreshing while configuring would replace the template being edited
    // Rest of the time, poll the backend for current state, as the state may come from this UI or from another backend service
    if (!this.state.configuring) this.refresh();
  }

  refresh() {
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
                     monitoring_sensors: state.monitoring_sensors});
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

          <button className="button-important" onClick={() => this.handleFeedNow()}>Feed Now</button>

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
                  const fmtDate = (d) => {
                    const dt = new Date(d);
                    const time = dt.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
                    const day = dt.getDate();
                    const mon = dt.toLocaleString([], {month: 'short'});
                    return `${time} ${day} ${mon}`;
                  };
                  const timeRequested = entry.time_requested ? fmtDate(entry.time_requested) : '-';
                  const timeAcknowledged = entry.time_acknowledged ? fmtDate(entry.time_acknowledged) : '?';
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
    }, () => {
      // Drop stale context so the hijack button doesn't stay enabled
      this.setState({ spotifyContext: null });
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
// Table rows are flex (see zmw.css): give the header and body cells of a column the same flex so they line up
const HISTORY_COL = (grow) => ({flex: `${grow} 1 0`});
const HISTORY_COLS = {
  time: HISTORY_COL(2),
  source: HISTORY_COL(1.5),
  phrase: HISTORY_COL(4),
  voice: HISTORY_COL(2),
  vol: HISTORY_COL(0.7),
  link: HISTORY_COL(0.7),
};

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
      fuzzyTts: true,
      isRecording: false,
      speakerList: null,
      ttsLanguages: null,
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
    mJsonGet(`${this.props.api_base_path}/ls_speakers`, (data) => {
      const enabled = {};
      if (data) data.forEach(s => enabled[s] = true);
      this.setState({ speakerList: data, enabledSpeakers: enabled });
    });
    mJsonGet(`${this.props.api_base_path}/tts_languages`, (data) => {
      const update = { ttsLanguages: data };
      if (data && data.length > 0) {
        const dflt = data.find(l => l.default);
        update.ttsLang = dflt ? dflt.value : data[0].value;
      }
      this.setState(update);
    });
    mJsonGet(`${this.props.api_base_path}/svc_config`, (data) => {
      const fuzzyAvailable = data.fuzzy_available !== false;
      const update = { httpsServer: data.https_server, fuzzyAvailable };
      if (!fuzzyAvailable) {
        update.fuzzyTts = false;
      }
      this.setState(update);
    });
    this.fetchAnnouncementHistory();
  }

  fetchAnnouncementHistory() {
    mJsonGet(`${this.props.api_base_path}/announcement_history`, (data) => this.setState({ announcementHistory: data }));
  }

  _doAnnounce(fuzzy) {
    const phrase = this.state.ttsPhrase.trim() || prompt("What is so important?");
    if (!phrase) return;
    this.setState({ ttsPhrase: phrase });

    const newEntry = {
      timestamp: new Date().toISOString(),
      source: "http",
      phrase: phrase,
      lang: this.state.ttsLang,
      volume: this.state.ttsVolume,
      uri: `${this.props.api_base_path}/tts/${phrase}_${this.state.ttsLang}.mp3`
    };

    this.setState(prev => ({
      announcementHistory: [...prev.announcementHistory, newEntry].slice(-10)
    }));

    const selectedSpeakers = this.state.enabledSpeakers
      ? Object.keys(this.state.enabledSpeakers).filter(s => this.state.enabledSpeakers[s])
      : [];
    const speakersParam = selectedSpeakers.length > 0 ? `&speakers=${encodeURIComponent(selectedSpeakers.join(','))}` : '';
    const url = `${this.props.api_base_path}/announce_tts?lang=${this.state.ttsLang}&phrase=${phrase}&vol=${this.state.ttsVolume}&fuzzy=${fuzzy}${speakersParam}`;
    mJsonGet(url, () => {
        this.setState({ ttsPhrase: "" });
        this.fetchAnnouncementHistory();
      });
  }

  onTTSRequested() {
    this._doAnnounce(this.state.fuzzyTts);
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

      mFetch(`${this.props.api_base_path}/announce_user_recording`, {
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

        {/* Voice options on one line, actions + volume on the next, so the panel fits a phone */}
        <div className="ctrl-box-with-range">
          <select
            style={{flex: "1 1 0", minWidth: 0, margin: 0}}
            value={this.state.ttsLang}
            onChange={e => this.setState({ ttsLang: e.target.value })}>
            {this.state.ttsLanguages && this.state.ttsLanguages.map(lang =>
              <option key={lang.value} value={lang.value}>{lang.label}</option>
            )}
          </select>

          <label style={{whiteSpace: "nowrap"}}>
            <input
              type="checkbox"
              checked={this.state.fuzzyTts}
              disabled={this.state.fuzzyAvailable === false}
              onChange={e => this.setState({ fuzzyTts: e.target.checked })}
            />
            Fuzzy TTS
          </label>
        </div>

        <div className="ctrl-box-with-range">
          <button onClick={this.onTTSRequested}>
            Shout
          </button>

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
              {this.state.speakerList.map(x => (
                <li key={x}>
                  <label>
                    <input
                      type="checkbox"
                      checked={!!(this.state.enabledSpeakers && this.state.enabledSpeakers[x])}
                      onChange={e => this.setState(prev => ({
                        enabledSpeakers: {...prev.enabledSpeakers, [x]: e.target.checked}
                      }))}
                    />
                    {x}
                  </label>
                </li>
              ))}
            </ul>
            <button onClick={() => this.setState(prev => {
              const allEnabled = prev.speakerList.every(s => prev.enabledSpeakers[s]);
              const updated = {};
              prev.speakerList.forEach(s => updated[s] = !allEnabled);
              return { enabledSpeakers: updated };
            })}>Toggle all</button>
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
                  <th style={HISTORY_COLS.time}>Time</th>
                  <th style={HISTORY_COLS.source}>Source</th>
                  <th style={HISTORY_COLS.phrase}>Phrase</th>
                  <th style={HISTORY_COLS.voice}>Voice</th>
                  <th style={HISTORY_COLS.vol}>Vol</th>
                  <th style={HISTORY_COLS.link}>Link</th>
                </tr>
              </thead>
              <tbody>
                {this.state.announcementHistory.slice().reverse().map((item, idx) => (
                  <tr key={idx}>
                    <td style={HISTORY_COLS.time}>{new Date(item.timestamp).toLocaleString()}</td>
                    <td style={HISTORY_COLS.source}>{item.source}</td>
                    <td style={{...HISTORY_COLS.phrase, flexDirection: "column"}}>
                      {item.phrase}
                      {item.fuzzy_text && <div><small><em>{item.fuzzy_text}</em></small></div>}
                    </td>
                    <td style={HISTORY_COLS.voice}>{item.voice || item.lang || "default"}</td>
                    <td style={HISTORY_COLS.vol}>{item.volume}</td>
                    <td style={HISTORY_COLS.link}><a href={item.uri}>🔊</a></td>
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
class ZmwSucks extends React.Component {
  static buildProps(api_base_path = '') {
    return {
      key: 'ZmwSucks',
      api_base_path,
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      robots: null,
      history: {},
    };
    this.fetchState = this.fetchState.bind(this);
    this.poller = null;
  }

  componentDidMount() {
    this.fetchState();
    this.poller = mPoll(this.fetchState, 5000);
  }

  componentWillUnmount() {
    this.poller?.stop();
  }

  fetchState() {
    mJsonGet(`${this.props.api_base_path}/get_state`, (res) => {
      this.setState({ robots: res });
    });
    mJsonGet(`${this.props.api_base_path}/get_history`, (res) => {
      this.setState({ history: res });
    });
  }

  sendCommand(cmd, alias) {
    mJsonPut(`${this.props.api_base_path}/${cmd}/${encodeURIComponent(alias)}`, {}, () => this.fetchState());
  }

  formatArea(sqft) {
    if (sqft === null || sqft === undefined) {
      return '?';
    }
    return `${(sqft * 0.0929).toFixed(1)} m²`;
  }

  formatInitiator(initiator) {
    const known = {
      localApp: 'ZMW',
      rmtApp: 'iRobot app',
      schedule: 'schedule',
      manual: 'button',
    };
    return known[initiator] || initiator || '?';
  }

  formatWifi(wifi) {
    if (wifi.rssi === null || wifi.rssi === undefined) {
      return '?';
    }
    const quality = wifi.rssi > -60 ? 'good' : (wifi.rssi > -70 ? 'ok' : 'weak');
    const snr = (wifi.snr === null || wifi.snr === undefined) ? '' : `, SNR ${wifi.snr} dB`;
    return `${quality} (${wifi.rssi} dBm${snr})`;
  }

  formatPosition(r) {
    if (r.position_supported === false) {
      return 'not supported by this robot';
    }
    if (!r.position) {
      return r.position_supported === null ? 'unknown (only checked away from the dock)' : 'no fix';
    }
    const p = r.position;
    const heading = Math.round(p.theta_rad * 180 / Math.PI);
    return `${p.x_m.toFixed(2)} m, ${p.y_m.toFixed(2)} m from dock, heading ${heading}°`;
  }

  renderMission(m) {
    if (!m.cycle || m.cycle === 'none') {
      return (<tr><td>Mission</td><td>none</td></tr>);
    }
    const started = m.start_time ? new Date(m.start_time * 1000).toLocaleTimeString() : '?';
    return (<>
      <tr><td>Mission</td><td>{m.cycle}, started {started} by {this.formatInitiator(m.initiator)}</td></tr>
      <tr><td>Duration</td><td>{m.minutes ?? '?'} min</td></tr>
      <tr><td>Cleaned</td><td>{this.formatArea(m.sqft)}</td></tr>
      {m.recharge_minutes > 0 && (<tr><td>Recharging</td><td>{m.recharge_minutes} min left</td></tr>)}
      {m.expire_minutes > 0 && (<tr><td>Expires</td><td>in {m.expire_minutes} min, if not resumed</td></tr>)}
    </>);
  }

  formatPct(part, total) {
    if (!total || part === null || part === undefined) {
      return '';
    }
    return ` (${Math.round(100 * part / total)}%)`;
  }

  renderLifetime(l, b) {
    const runtime = (l.runtime_hours === null || l.runtime_hours === undefined)
      ? '?' : `${l.runtime_hours} h ${l.runtime_minutes ?? 0} min`;
    return (
      <details>
        <summary>Lifetime stats</summary>
        <table style={{width: '100%', maxWidth: '500px', tableLayout: 'fixed'}}>
          <tbody>
            <tr><td>Runtime</td><td>{runtime}</td></tr>
            <tr><td>Area cleaned</td><td>{this.formatArea(l.sqft)}</td></tr>
            <tr><td>Missions</td><td>{l.missions ?? '?'}</td></tr>
            <tr><td>Completed</td><td>{l.missions_ok ?? '?'}{this.formatPct(l.missions_ok, l.missions)}</td></tr>
            <tr><td>Failed</td><td>{l.missions_failed ?? '?'}{this.formatPct(l.missions_failed, l.missions)}</td></tr>
            <tr><td>Cancelled</td><td>{l.missions_cancelled ?? '?'}{this.formatPct(l.missions_cancelled, l.missions)}</td></tr>
            <tr><td>Average mission</td><td>{l.avg_mission_minutes ?? '?'} min</td></tr>
            <tr><td>Got stuck</td><td>{l.stuck_count ?? '?'} times</td></tr>
            <tr><td>Battery cycles</td><td>{b.charge_cycles ?? '?'}</td></tr>
            <tr><td>Battery capacity</td><td>{b.est_capacity_mah ?? '?'} mAh (estimated)</td></tr>
            <tr><td>Battery made</td><td>{b.manufacture_date || '?'}</td></tr>
          </tbody>
        </table>
      </details>
    );
  }

  setSetting(alias, setting, value) {
    const url = `${this.props.api_base_path}/set_setting/${encodeURIComponent(alias)}/${setting}/${value}`;
    // The robot takes a moment to report the new value
    mJsonPut(url, {}, () => setTimeout(this.fetchState, 1500));
  }

  renderSettings(r) {
    const s = r.settings;
    return (
      <details>
        <summary>Settings</summary>
        <table style={{width: '100%', maxWidth: '500px', tableLayout: 'fixed'}}>
          <tbody>
            <tr><td>Passes</td><td>
              <select value={s.passes} onChange={(e) => this.setSetting(r.alias, 'passes', e.target.value)}>
                <option value="auto">Auto</option>
                <option value="one">One</option>
                <option value="two">Two</option>
              </select>
            </td></tr>
            <tr><td>Pause when bin full</td><td>
              <input type="checkbox" checked={s.bin_pause}
                     onChange={(e) => this.setSetting(r.alias, 'bin_pause', e.target.checked)} />
            </td></tr>
            <tr><td>Child lock</td><td>
              <input type="checkbox" checked={s.child_lock}
                     onChange={(e) => this.setSetting(r.alias, 'child_lock', e.target.checked)} />
            </td></tr>
          </tbody>
        </table>
      </details>
    );
  }

  // The schedule the robot follows: its own (eg set in the iRobot app) if it has one, else the one in the
  // service config. Same rule as the service's MissionMonitor.
  renderSchedule(r) {
    const own = r.schedule;
    const cfg = r.service_schedule;
    // cfg.ignored comes from the service, so the UI can't disagree with what it actually does
    const useCfg = cfg && !cfg.ignored;
    const hasOwn = own && own.entries && own.entries.length > 0;
    if (!useCfg && !hasOwn) {
      return (<p><small>No schedule set</small></p>);
    }
    const sch = useCfg ? cfg : own;
    const source = useCfg ? 'config' : 'device';
    const pad = (n) => String(n ?? 0).padStart(2, '0');
    return (
      <details>
        <summary>Schedule{sch.paused ? ' (on hold)' : ''}</summary>
        <p><small>Source: {source}</small></p>
        {cfg && cfg.ignored && (
          <p className="warn"><small>The schedule in the service config is ignored, because the robot has its
            own. Remove one of them.</small></p>
        )}
        <table style={{width: '100%', maxWidth: '500px', tableLayout: 'fixed'}}>
          <thead><tr><th>Days</th><th>Time</th><th>Active</th></tr></thead>
          <tbody>
            {sch.entries.map((e, i) => (
              <tr key={i}>
                <td>{e.days.join(', ')}</td>
                <td>{pad(e.hour)}:{pad(e.min)}{e.command && e.command !== 'start' ? ` (${e.command})` : ''}</td>
                <td>{e.enabled && !sch.paused ? 'yes' : 'no'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sch.timezone && (<p><small>Times in the robot's timezone, {sch.timezone}</small></p>)}
        {source === 'config' && (<p><small>Times local to the service</small></p>)}
      </details>
    );
  }

  formatRunResult(run) {
    const known = {
      running: 'running',
      ok: 'completed',
      failed: 'failed',
      cancelled: 'cancelled',
      unknown: 'ended, not completed',
      missed: 'didn\'t start',
    };
    const txt = known[run.result] || run.result;
    return (run.result === 'ok' || run.result === 'running') ? txt : (<span className="warn">{txt}</span>);
  }

  renderHistory(alias) {
    const runs = this.state.history[alias] || [];
    if (runs.length === 0) {
      return (<p><small>No runs yet</small></p>);
    }
    const fmtTime = (secs) => secs ? new Date(secs * 1000).toLocaleString() : '?';
    return (
      <details>
        <summary>History</summary>
        <table style={{width: '100%', maxWidth: '500px'}}>
          <thead><tr><th>Started</th><th>By</th><th>Result</th><th>Duration</th><th>Cleaned</th></tr></thead>
          <tbody>
            {runs.map((run, i) => (<React.Fragment key={i}>
              <tr>
                <td>{fmtTime(run.start)}</td>
                <td>{run.scheduled
                       ? `schedule${run.scheduled_time ? ` ${run.scheduled_time}` : ''}`
                       : this.formatInitiator(run.initiator)}</td>
                <td>{this.formatRunResult(run)}</td>
                <td>{run.minutes ?? '-'}{run.minutes !== null && run.minutes !== undefined ? ' min' : ''}</td>
                <td>{run.sqft !== null && run.sqft !== undefined ? this.formatArea(run.sqft) : '-'}</td>
              </tr>
              {(run.problems.length > 0 || run.details) && (
                <tr><td colSpan="5"><small>
                  {run.problems.length > 0 && `Problems: ${run.problems.join(', ')}. `}
                  {run.details}
                  {run.end && ` Ended ${fmtTime(run.end)}.`}
                </small></td></tr>
              )}
            </React.Fragment>))}
          </tbody>
        </table>
      </details>
    );
  }

  renderRobot(r) {
    if (!r.connected) {
      return (
        <div key={r.alias} className="card warn">
          <p><b>{r.alias}</b>: not connected</p>
          {this.renderHistory(r.alias)}
        </div>
      );
    }

    const rawStateUrl = `${this.props.api_base_path}/get_raw_state/${encodeURIComponent(r.alias)}`;
    return (
      <div key={r.alias} className="card hint">
        <p><b>{r.alias}</b>: {r.state || '?'}</p>
        <table style={{width: '100%', maxWidth: '500px', tableLayout: 'fixed'}}>
          <tbody>
            <tr><td>Battery</td><td>{r.battery_pct ?? '?'}%</td></tr>
            <tr><td>Phase</td><td>{r.phase || '?'}</td></tr>
            <tr><td>Bin</td><td>{r.bin_full ? <span className="warn">full</span> : 'ok'}</td></tr>
            {r.error && (<tr><td>Error</td><td className="warn">{r.error}</td></tr>)}
            {this.renderMission(r.mission)}
            <tr><td>Position</td><td>{this.formatPosition(r)}</td></tr>
            <tr><td>Wi-Fi</td><td>{this.formatWifi(r.wifi)}</td></tr>
            <tr><td>IP</td><td>{r.ip}</td></tr>
          </tbody>
        </table>
        {this.renderSchedule(r)}
        {this.renderSettings(r)}
        {this.renderHistory(r.alias)}
        {this.renderLifetime(r.lifetime, r.battery)}
        <button onClick={() => this.sendCommand('start', r.alias)}>Start</button>
        <button onClick={() => this.sendCommand('pause', r.alias)}>Pause</button>
        <button onClick={() => this.sendCommand('dock', r.alias)}>Dock</button>
        <button onClick={() => this.sendCommand('find', r.alias)}>Find</button>
        <p><small><a href={rawStateUrl} target="_blank" rel="noreferrer">Raw state (debug)</a></small></p>
      </div>
    );
  }

  render() {
    if (!this.state.robots) {
      return (<div className="app-loading">Loading...</div>);
    }

    const robots = Object.values(this.state.robots);
    if (robots.length === 0) {
      return (<p>No robots configured</p>);
    }
    return (<div>{robots.map((r) => this.renderRobot(r))}</div>);
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
    this.poller = mPoll(() => this.fetchAlerts(), 30000);
  }

  componentWillUnmount() {
    this.poller?.stop();
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
    // Alerts come as "ServiceName: message"; show the service name as the card's title
    return (
      <div className="dash-alerts">
        {this.state.alerts.map((alert, idx) => {
          const sep = alert.indexOf(': ');
          return (
            <div key={idx} className="dash-alert" role="alert">
              {sep > 0 ? <><b>{alert.slice(0, sep)}</b><span>{alert.slice(sep + 2)}</span></> : <span>{alert}</span>}
            </div>
          );
        })}
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
        {z2mEmbedApp(
          MqttLights,
          MqttLights.buildProps('/ZmwLights', this.state.scenes, this.props.groupBadges, this.props.groupExtras))}
      </section>
    );
  }
}

// Things named after a light group belong to that group's tile: "CocinaTempSensor" goes in "Cocina". Group names
// are tried longest first, so a group named "TVRoomBack" wins over "TVRoom". Returns the group's name, or undefined.
function findGroupFor(thingName, groupNames) {
  return [...groupNames].sort((a, b) => b.length - a.length).find(g => thingName.startsWith(g));
}

function useLightGroupNames() {
  const [names, setNames] = React.useState(null);
  React.useEffect(() => {
    mJsonGet('/ZmwLights/get_groups', (res) => setNames((res || []).map(g => g.name)));
  }, []);
  return names;
}

// A temperature sensor is shown on its room's tile; a room with several sensors shows all of them. Sensors that match
// no group go in the sensors list.
function splitSensorsByGroup(groupNames, temperatures) {
  const groupBadges = {};
  const otherSensors = [];
  for (const sensor of Object.keys(temperatures).sort()) {
    const value = temperatures[sensor];
    if (value == null) continue;
    const group = findGroupFor(sensor, groupNames);
    if (group) {
      groupBadges[group] = [...(groupBadges[group] || []), `${Number(value).toFixed(1)}°`];
    } else {
      otherSensors.push([sensor, Number(value)]);
    }
  }
  return { groupBadges, otherSensors };
}

function useRoomTemperatures(groupNames) {
  const [temps, setTemps] = React.useState(null);
  React.useEffect(() => {
    mJsonGet('/ZmwSensormon/sensors/get_all/temperature', (res) => setTemps(res || {}));
  }, []);
  return React.useMemo(() => {
    if (!groupNames || !temps) return { groupBadges: {}, otherSensors: [] };
    return splitSensorsByGroup(groupNames, temps);
  }, [groupNames, temps]);
}

const SONOS_API = '/ZmwSonosCtrl';
const SONOS_CACHE_KEY = 'sonos_world_state';
// Same as the Sonos service's SONOS_STATE_CACHE_TTL_SECS: a reply older than this is being refreshed by the service
const SONOS_STATE_TTL_SECS = 30;

const DASH_ICON_PLAY = (
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>);
const DASH_ICON_PAUSE = (
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>);

// Sonos speakers. The Sonos service has to talk to every speaker, so it may answer much later than the lights; this
// never holds them up. It starts from the last state saved in local storage, with the controls disabled until the
// service confirms each speaker is there. A speaker we knew about that doesn't answer stays listed, disabled, until
// the next load.
function useSpeakers() {
  const storage = React.useMemo(() => new LocalStorageManager(), []);
  const [world, setWorld] = React.useState(() => {
    const cached = storage.cacheGet_ignoreExpire(SONOS_CACHE_KEY) || {};
    return { speakers: cached.speakers || [], groups: cached.groups || {}, live: {}, loaded: false };
  });

  const refresh = React.useCallback((retryIfStale = true) => {
    mAjax({
      url: `${SONOS_API}/world_state`,
      type: 'GET',
      dataType: 'JSON',
      success: (res) => {
        storage.cacheSave(SONOS_CACHE_KEY, { speakers: res.speakers, groups: res.groups });
        setWorld(prev => {
          const live = Object.fromEntries(res.speakers.map(spk => [spk.name, true]));
          const gone = prev.speakers.filter(spk => !live[spk.name]);
          return { speakers: [...res.speakers, ...gone], groups: res.groups, live, loaded: true };
        });
        // An old copy means the service is reading the speakers again in the background: fetch the new state
        if (retryIfStale && res.age_secs > SONOS_STATE_TTL_SECS) {
          setTimeout(() => refresh(false), 3000);
        }
      },
      // Sonos being down isn't worth a popup: its speakers just stay disabled
      error: () => setWorld(prev => ({ ...prev, live: {}, loaded: true })),
    });
  }, []);

  React.useEffect(() => refresh(), []);

  const setVolume = (name, volume) => {
    setWorld(prev => ({
      ...prev,
      speakers: prev.speakers.map(spk => spk.name === name ? { ...spk, volume } : spk),
    }));
    mJsonPut(`${SONOS_API}/volume`, { [name]: volume });
  };
  const togglePlay = (name) => mJsonPut(`${SONOS_API}/play_pause`, { speaker: name }, () => refresh(false));

  return { ...world, refresh, setVolume, togglePlay };
}

function speakerSubtitle(spk, sonos) {
  if (!sonos.loaded) return 'Connecting...';
  if (!sonos.live[spk.name]) return 'Offline';
  let what = 'Stopped';
  if (spk.is_playing_tv) what = 'TV';
  else if (spk.is_playing_line_in) what = 'Line in';
  else if (spk.transport_state === 'PLAYING') what = 'Playing';
  else if (spk.transport_state === 'PAUSED_PLAYBACK') what = 'Paused';
  // Play/pause works on a whole group, so say which speakers are in it
  const group = Object.values(sonos.groups).find(members => members.includes(spk.name)) || [];
  const others = group.filter(name => name !== spk.name);
  return others.length ? `${what} · with ${others.join(', ')}` : what;
}

function SpeakerRow(props) {
  const { spk, room, sonos } = props;
  const live = !!sonos.live[spk.name];
  const playing = spk.transport_state === 'PLAYING';
  // TV and line in can't be paused, and a stopped speaker may have nothing to resume
  const canToggle = live && !spk.is_playing_tv && !spk.is_playing_line_in
    && (playing || spk.transport_state === 'PAUSED_PLAYBACK');
  const displayName = (spk.name.startsWith(room) && spk.name !== room) ? spk.name.slice(room.length) : spk.name;
  return (
    <div className="zl-row zl-spk">
      <span className="zl-name">
        <img src={`${SONOS_API}/favicon.ico`} alt="" />
        {prettyThingName(displayName)}<small>{speakerSubtitle(spk, sonos)}</small>
      </span>
      <button type="button" className="zl-more" disabled={!canToggle}
              aria-label={`${displayName}: ${playing ? 'pause' : 'play'}`}
              onClick={() => sonos.togglePlay(spk.name)}>
        {playing ? DASH_ICON_PAUSE : DASH_ICON_PLAY}
      </button>
      <DebouncedRange className="zl-bri" min={0} max={100} value={spk.volume ?? 0}
                      disabled={!live || spk.volume == null}
                      onChange={(e) => sonos.setVolume(spk.name, Number(e.target.value))} />
    </div>
  );
}

// Rendered only while its room is open: opening a room is a good moment to pick up changes made elsewhere
function RoomSpeakers(props) {
  React.useEffect(() => props.sonos.refresh(false), []);
  return props.speakers.map(spk => <SpeakerRow key={spk.name} spk={spk} room={props.room} sonos={props.sonos} />);
}

// {room: <RoomSpeakers/>} for every room with a speaker. Rooms without one get nothing, not even the separator.
// Speakers that match no room aren't shown here; the Sonos panel under "More" still has them.
function speakersByRoom(groupNames, sonos) {
  const byRoom = {};
  for (const spk of sonos.speakers) {
    const room = groupNames && findGroupFor(spk.name, groupNames);
    if (room) byRoom[room] = [...(byRoom[room] || []), spk];
  }
  const extras = {};
  for (const [room, speakers] of Object.entries(byRoom)) {
    extras[room] = <RoomSpeakers key={room} room={room} speakers={speakers} sonos={sonos} />;
  }
  return extras;
}

function SensorsSection(props) {
  if (props.sensors.length === 0) {
    return null;
  }
  const sensormon = ProxiedServices.get('ZmwSensormon');
  return (
    <section id="sensors-list-section">
      <h4 className="dash-heading"><a href={sensormon}>Sensors</a></h4>
      <div className="dash-minis">
        {props.sensors.map(([name, value]) => (
          <a key={name} href={sensormon ? `${sensormon}/index.html?sensor=${encodeURIComponent(name)}` : undefined}>
            {name}<b>{value.toFixed(1)}°</b>
          </a>
        ))}
      </div>
    </section>
  );
}

function CatSection(props) {
  return (
    <section id="catsnacks-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwCatSnackDispenser')}><img src="/ZmwCatSnackDispenser/favicon.ico"/></a>
      {z2mEmbedApp(
        CatFeeder,
        CatFeeder.buildProps('/ZmwCatSnackDispenser'))}
    </section>
  );
}

function TTSAnnounceSection(props) {
  return (
    <section id="ttsannounce-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwSpeakerAnnounce')}><img src="/ZmwSpeakerAnnounce/favicon.ico"/></a>
      {z2mEmbedApp(
        TTSAnnounce,
        TTSAnnounce.buildProps('/ZmwSpeakerAnnounce'))}
    </section>
  );
}

function DoormanSection(props) {
  return (
    <section id="doorman-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwDoorman')}><img src="/ZmwDoorman/favicon.ico"/></a>
      {z2mEmbedApp(
        DoorMan,
        DoorMan.buildProps('/ZmwDoorman'))}
    </section>
  );
}

function SucksSection(props) {
  return (
    <section id="sucks-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwSucks')}><img src="/ZmwSucks/favicon.ico"/></a>
      {z2mEmbedApp(
        ZmwSucks,
        ZmwSucks.buildProps('/ZmwSucks'))}
    </section>
  );
}

function MqttHeatingSection(props) {
  return (
    <section id="heating-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwHeating')}><img src="/ZmwHeating/favicon.ico"/></a>
      {z2mEmbedApp(
        HeatingControls,
        HeatingControls.buildProps('/ZmwHeating'))}
    </section>
  );
}

function SonosCtrlSection(props) {
  return (
    <section id="sonos-ctrl-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwSonosCtrl')}><img src="/ZmwSonosCtrl/favicon.ico"/></a>
      {z2mEmbedApp(
        SonosCtrl,
        SonosCtrl.buildProps('/ZmwSonosCtrl', ProxiedServices.get('ZmwSonosCtrl')))}
    </section>
  );
}

function ConfigSection(props) {
  const [userLinks, setUserLinks] = React.useState([]);

  React.useEffect(() => {
    mJsonGet('/get_user_defined_links', (links) => {
      setUserLinks(links || []);
    });
  }, []);

  const handleClearCache = () => {
    localStorage.clear();
    location.reload();
  };

  return (
    <section id="config-section">
      <img className="section-badge" src="/settings.ico"/>
      <div style={{display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '0.5rem', alignItems: 'center'}}>
        <label>Fixes:</label>
        <div><button alt="This fixes things if something is out of sync" onClick={handleClearCache}>Clear cache</button></div>

        <label>More:</label>
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
  const groupNames = useLightGroupNames();
  const { groupBadges, otherSensors } = useRoomTemperatures(groupNames);
  const sonos = useSpeakers();

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
      <LightsSection groupBadges={groupBadges} groupExtras={speakersByRoom(groupNames, sonos)} />
      <SensorsSection sensors={otherSensors} />

      <h4 className="dash-heading">More</h4>
      <section id="zmw_other_services">
        { renderSvcBtn('Shout', 'ZmwSpeakerAnnounce') }
        { renderSvcBtn('Cat', 'ZmwCatSnackDispenser') }
        { renderSvcBtn('Door', 'ZmwDoorman') }
        { renderSvcBtn('Sucks', 'ZmwSucks') }
        { renderSvcBtn('Heat', 'ZmwHeating') }
        { renderSvcBtn('Sonos', 'ZmwSonosCtrl') }
        <button onClick={() => window.open(ProxiedServices.get('ZmwServicemon'), '_blank')}>
          <img src="/ZmwServicemon/favicon.ico" alt=""/>
          Svcs
        </button>
        { renderIcoBtn('Settings', '/settings.ico') }
      </section>

      <div ref={contentRef}>
        {expandedSection === 'Shout' && <TTSAnnounceSection />}
        {expandedSection === 'Cat' && <CatSection />}
        {expandedSection === 'Door' && <DoormanSection />}
        {expandedSection === 'Sucks' && <SucksSection />}
        {expandedSection === 'Heat' && <MqttHeatingSection />}
        {expandedSection === 'Sonos' && <SonosCtrlSection />}
        {expandedSection === 'Settings' && <ConfigSection />}
      </div>
    </main>
  );
}

Dashboard.buildProps = () => ({ key: 'dashboard' });

// Initialize: fetch prefetch data and start React app in parallel. Colors come from dashboard.css and follow the
// phone's light/dark setting, so there's no theme to restore.
ProxiedServices.init(() => {}); // Fetch in background for badge links
z2mStartReactApp('#app_root', Dashboard);
