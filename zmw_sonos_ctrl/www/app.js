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
