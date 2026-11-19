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
        {React.createElement(
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
