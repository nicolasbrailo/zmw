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
