function _formatDate(timestamp) {
  const d = new Date(timestamp);
  return `${d.getDate()}/${d.getMonth()+1} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
}

class ServiceMonitor extends React.Component {
  static buildProps() {
    return {
      key: "ServiceMonitor",
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      services: null,
      systemdServicesStdout: null,
      monitoredSystemdServices: null,
      uptimeStdout: null,
      recentErrors: null,
    };
  }

  componentDidMount() {
    this.on_app_became_visible();
  }

  on_app_became_visible() {
    mJsonGet('/ls', (data) => {
      this.setState({ services: data });
    });
    mJsonGet('/recent_errors', (data) => {
      this.setState({ recentErrors: data });
    });
    mJsonGet('/systemd_services_status', (data) => {
      this.setState({ monitoredSystemdServices: data });
    });
    mTextGet('/systemd_status',
      (stdout) => { this.setState({ systemdServicesStdout: stdout }); });
    mTextGet('/system_uptime',
      (stdout) => { this.setState({ uptimeStdout: stdout }); });
  }

  isStale(lastSeen) {
    if (!lastSeen) return true;
    // Convert "YYYY-MM-DD HH:mm:ss.microsec" → timestamp
    const last = new Date(lastSeen.replace(" ", "T"));
    const now = new Date();
    const diffMs = now - last;
    const diffMinutes = diffMs / 1000 / 60;
    return diffMinutes > 5;
  }

  formatServiceName(srv) {
    let name = srv.name;
    if (name.startsWith('Zmw')) {
      name = name.slice(3);
    }
    if (srv.www) {
      try {
        const url = new URL(srv.www);
        const port = url.port || (url.protocol === 'https:' ? '443' : '80');
        name = `${name}:${port}`;
      } catch (e) {}
    }
    return name;
  }

  renderServices() {
    if (!this.state.services) return <div>Loading services...</div>;

    const services = Object.values(this.state.services);
    const total = services.length;
    const running = services.filter(srv => !this.isStale(srv.last_seen)).length;
    const unhealthy = total - running;
    let statusSummary = `${running} out of ${total} services up and running`;
    if (unhealthy > 0) {
      statusSummary += `, ${unhealthy} service${unhealthy > 1 ? 's' : ''} unhealthy`;
    }

    return <section id="zmw_services" className="card">
      <h3>ZMW Services</h3>
        <p>{statusSummary}</p>
        <div className="card-grid">
        {services.map((srv) => (
          <div key={srv.name} className="card">
            <h4>
            {srv.www ? (
              <a href={srv.www} target="_blank" rel="noopener noreferrer">
                <img src={`${srv.www}/favicon.ico`} className="icon-inline" />
                {this.formatServiceName(srv)}
              </a>
            ) : (
              <strong>{this.formatServiceName(srv)}</strong>
            )}
            </h4>

            <div className={this.isStale(srv.last_seen) ? 'text-small text-error' : 'text-small'}>
              {srv.last_seen || "Service down"}
            </div>

            {(srv.methods && (srv.methods.length > 0) && (
            <div className="text-small text-secondary">
              <em>Methods:</em> {srv.methods.join(", ")}
            </div>
            ))}

            {srv.www && (
              <a href={`${srv.www}/svc_logs.html`} target="_blank" rel="noopener noreferrer"
                 className="card-corner">
                📜 Logs
              </a>
            )}
          </div>
        ))}
        </div>
      </section>
  }

  renderMonitoredSystemdServices() {
    if (!this.state.monitoredSystemdServices) return null;
    if (this.state.monitoredSystemdServices.length === 0) return null;

    const services = this.state.monitoredSystemdServices;
    const total = services.length;
    const running = services.filter(srv => srv.running).length;
    const unhealthy = total - running;
    let statusSummary = `${running} out of ${total} services up and running`;
    if (unhealthy > 0) {
      statusSummary += `, ${unhealthy} service${unhealthy > 1 ? 's' : ''} unhealthy`;
    }

    return <section id="monitored_systemd_services" className="card">
      <h3>Monitored Systemd non-ZMW Services</h3>
        <p>{statusSummary}</p>
        <div className="card-grid">
        {services.map((srv) => (
          <div key={srv.name} className="card">
            <h4>
              <strong>{srv.name}</strong>
            </h4>

            <div className={srv.running ? 'text-small text-ok' : 'text-small text-error'}>
              {srv.status}
            </div>

            <a href={`/systemd_logs?service=${encodeURIComponent(srv.name)}`} target="_blank" rel="noopener noreferrer"
               className="card-corner">
              Logs
            </a>
          </div>
        ))}
        </div>
      </section>
  }

  renderSystemdStatus() {
    let statusSummary = null;
    if (this.state.systemdServicesStdout) {
      const lines = this.state.systemdServicesStdout.split('\n').filter(line => line.trim());
      const total = lines.length;
      const running = lines.filter(line => line.includes('active') && line.includes('running')).length;
      const unhealthy = total - running;
      statusSummary = `${running} out of ${total} services up and running`;
      if (unhealthy > 0) {
        statusSummary += `, ${unhealthy} service${unhealthy > 1 ? 's' : ''} unhealthy`;
      }
    }

    return <section id="systemd_status" className="card">
      <h3>Systemd services status</h3>
      {!this.state.systemdServicesStdout ? (
        <div className="app-loading">Loading systemd status...</div>
      ):(
        <div>
          <p>{statusSummary}</p>
          { this.state.uptimeStdout && <p>{this.state.uptimeStdout}</p> }
          <pre dangerouslySetInnerHTML={{__html: this.state.systemdServicesStdout}}></pre>
        </div>
      )}
    </section>
  }

  clearRecentErrors() {
    mJsonGet('/recent_errors_clear', () => {
      mJsonGet('/recent_errors', (data) => {
        this.setState({ recentErrors: data });
      });
    });
  }

  simulateError() {
    mJsonGet('/recent_errors_test_new', () => {
      mJsonGet('/recent_errors', (data) => {
        this.setState({ recentErrors: data });
      });
    });
  }

  renderRecentErrors() {
    if (!this.state.recentErrors) return <div>Loading errors...</div>;

    const errors = this.state.recentErrors;
    if (errors.length === 0) {
      return <section id="journal_errors" className="card">
        <h3>Recent Errors ({errors.length})</h3>
        <button onClick={() => this.simulateError()}>Simulate error</button>
        <p>No errors detected! All services running cleanly.</p>
      </section>;
    }

    return (
      <section id="journal_errors" className="card">
      <h3>Recent Errors ({errors.length})</h3>
      <button onClick={() => this.clearRecentErrors()}>Clear</button>
      <button onClick={() => this.simulateError()}>Simulate error</button>
      <table>
        <tbody>
          {errors.slice().reverse().map((err, idx) => {
            const priorityColors = {
              'EMERG': '#ff0000',
              'ALERT': '#ff3300',
              'CRIT': '#ff6600',
              'ERR': '#ff9900',
              'WARNING': '#ffcc00'
            };
            const priorityText = {
              'EMERG': 'EMRG',
              'ALERT': 'ALRT',
              'CRIT': 'CRIT',
              'ERR': 'ERRR',
              'WARNING': 'WARN',
            };
            return (
              <tr key={idx}>
                <td>{_formatDate(err.timestamp)}</td>
                <td>{err.service}</td>
                <td style={{ color: priorityColors[err.priority_name] || '#999' }}>
                  {priorityText[err.priority_name] || err.priority_name}
                </td>
                <td className="journal-entry">{err.message}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>);
  }

  render() {
    return (
      <div id="ServiceMonitorContainer">
        {this.renderServices()}
        {this.renderMonitoredSystemdServices()}
        {this.renderSystemdStatus()}
        {this.renderRecentErrors()}
      </div>
    );
  }
};
