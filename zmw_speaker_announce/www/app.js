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
