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
