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
        {React.createElement(
          MqttLights,
          MqttLights.buildProps('/ZmwLights', this.state.scenes, this.props.groupBadges))}
      </section>
    );
  }
}

// A temperature sensor whose name starts with a light group's name ("CocinaTempSensor" -> "Cocina") is shown on that
// group's tile; a room with several sensors shows all of them. Sensors that match no group go in the sensors list.
function splitSensorsByGroup(groupNames, temperatures) {
  const groupBadges = {};
  const otherSensors = [];
  // Longest names first, so a group named "TVRoomBack" wins over "TVRoom"
  const names = [...groupNames].sort((a, b) => b.length - a.length);
  for (const sensor of Object.keys(temperatures).sort()) {
    const value = temperatures[sensor];
    if (value == null) continue;
    const group = names.find(g => sensor.startsWith(g));
    if (group) {
      groupBadges[group] = [...(groupBadges[group] || []), `${Number(value).toFixed(1)}°`];
    } else {
      otherSensors.push([sensor, Number(value)]);
    }
  }
  return { groupBadges, otherSensors };
}

function useRoomTemperatures() {
  const [split, setSplit] = React.useState({ groupBadges: {}, otherSensors: [] });
  React.useEffect(() => {
    let groups = null;
    let temps = null;
    const done = () => {
      if (groups && temps) setSplit(splitSensorsByGroup(groups.map(g => g.name), temps));
    };
    mJsonGet('/ZmwLights/get_groups', (res) => { groups = res || []; done(); });
    mJsonGet('/ZmwSensormon/sensors/get_all/temperature', (res) => { temps = res || {}; done(); });
  }, []);
  return split;
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

function SucksSection(props) {
  return (
    <section id="sucks-section">
      <a className="section-badge" href={ProxiedServices.get('ZmwSucks')}><img src="/ZmwSucks/favicon.ico"/></a>
      {React.createElement(
        ZmwSucks,
        ZmwSucks.buildProps('/ZmwSucks'))}
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
  const { groupBadges, otherSensors } = useRoomTemperatures();

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
      <LightsSection groupBadges={groupBadges} />
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
