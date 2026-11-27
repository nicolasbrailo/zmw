class ShellyPlugMonitor extends React.Component {
  static buildProps() {
    return {
      key: 'ShellyPlugMonitor',
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      devices: null,
    };
    this.fetchStats = this.fetchStats.bind(this);
    this.poller = null;
  }

  async componentDidMount() {
    this.fetchStats();
    this.poller = mPoll(this.fetchStats, 10000);
  }

  componentWillUnmount() {
    this.poller?.stop();
  }

  fetchStats() {
    mJsonGet('/all_stats', (res) => {
      this.setState({ devices: res });
    });
  }

  formatNumber(value, decimals) {
    if (value === null || value === undefined) {
      return '?';
    }
    return value.toFixed(decimals);
  }

  formatUptime(seconds) {
    const months = Math.floor(seconds / (30 * 24 * 3600));
    seconds %= 30 * 24 * 3600;
    const days = Math.floor(seconds / (24 * 3600));
    seconds %= 24 * 3600;
    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;

    const parts = [];
    if (months > 0) parts.push(`${months} month${months !== 1 ? 's' : ''}`);
    if (days > 0) parts.push(`${days} day${days !== 1 ? 's' : ''}`);
    if (hours > 0) parts.push(`${hours} hour${hours !== 1 ? 's' : ''}`);
    if (mins > 0) parts.push(`${mins} min${mins !== 1 ? 's' : ''}`);
    if (secs > 0 || parts.length === 0) parts.push(`${secs} sec${secs !== 1 ? 's' : ''}`);

    return parts.join(', ');
  }

  renderDevice(name, stats) {
    const powerStatus = stats.powered_on ? 'Power: ON' : 'Power: OFF';
    const powerClass = stats.powered_on ? 'bg-success' : 'bg-error';
    const uptime = stats.device_uptime !== null && stats.device_uptime !== undefined
      ? this.formatUptime(stats.device_uptime)
      : '?';
    const ipDisplay = stats.device_ip
      ? stats.device_ip
      : <span className="warn">device is offline</span>;
    const cardClass = stats.online ? 'card hint' : 'card warn';

    return (
      <div key={name} className={cardClass}>
        <p><b>{name}</b>, {powerStatus} - <small>updated: {stats.device_current_time || '?'}</small></p>
        <table className="narrow-table">
          <tbody>
            <tr><td>Power</td><td>{this.formatNumber(stats.active_power_watts, 1)} W</td></tr>
            <tr><td>Current</td><td>{this.formatNumber(stats.current_amps, 3)} A</td></tr>
            <tr><td>Voltage</td><td>{this.formatNumber(stats.voltage_volts, 1)} V</td></tr>
            <tr><td>Temperature</td><td>{this.formatNumber(stats.temperature_c, 1)} °C</td></tr>
            <tr><td>Energy (last min)</td><td>{this.formatNumber(stats.last_minute_energy_use_watt_hour, 3)} Wh</td></tr>
            <tr><td>Energy (lifetime)</td><td>{this.formatNumber(stats.lifetime_energy_use_watt_hour, 3)} Wh</td></tr>
            <tr><td>Uptime</td><td>{uptime}</td></tr>
            <tr><td>IP</td><td>{ipDisplay}</td></tr>
          </tbody>
        </table>
      </div>
    );
  }

  render() {
    if (!this.state.devices) {
      return (<div className="app-loading">Loading...</div>);
    }

    const deviceNames = Object.keys(this.state.devices);
    return (
      <div id="ShellyPlugContainer">
        {deviceNames.length === 0 ? (
          <p>No devices found</p>
        ) : (
          <div>
            {deviceNames.map((name) => this.renderDevice(name, this.state.devices[name]))}
          </div>
        )}
      </div>
    );
  }
}
