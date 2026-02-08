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
