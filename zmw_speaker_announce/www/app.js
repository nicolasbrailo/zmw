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
    mJsonGet(`${this.props.api_base_path}/ls_speakers`, (data) => this.setState({ speakerList: data }));
    mJsonGet(`${this.props.api_base_path}/tts_languages`, (data) => {
      const update = { ttsLanguages: data };
      if (data && data.length > 0 && !data.find(l => l.value === this.state.ttsLang)) {
        update.ttsLang = data[0].value;
      }
      this.setState(update);
    });
    mJsonGet(`${this.props.api_base_path}/svc_config`, (data) => this.setState({ httpsServer: data.https_server }));
    this.fetchAnnouncementHistory();
  }

  fetchAnnouncementHistory() {
    mJsonGet(`${this.props.api_base_path}/announcement_history`, (data) => this.setState({ announcementHistory: data }));
  }

  onTTSRequested() {
    const phrase = this.state.ttsPhrase.trim() || prompt("What is so important?");
    if (!phrase) return;
    this.setState({ ttsPhrase: phrase });

    console.log(`announce {"lang": "${this.state.ttsLang}", "phrase": "${phrase}"}`);

    const newEntry = {
      timestamp: new Date().toISOString(),
      phrase: phrase,
      lang: this.state.ttsLang,
      volume: this.state.ttsVolume,
      uri: `${this.props.api_base_path}/tts/${phrase}_${this.state.ttsLang}.mp3`
    };

    this.setState(prev => ({
      announcementHistory: [...prev.announcementHistory, newEntry].slice(-10)
    }));

    console.log(`${this.props.api_base_path}/announce_tts?lang=${this.state.ttsLang}&phrase=${phrase}&vol=${this.state.ttsVolume}`)
    mJsonGet(
      `${this.props.api_base_path}/announce_tts?lang=${this.state.ttsLang}&phrase=${phrase}&vol=${this.state.ttsVolume}`,
      () => {
        console.log("Sent TTS request");
        this.setState({ ttsPhrase: "" });
        this.fetchAnnouncementHistory();
      });
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

        <div className="ctrl-box-with-range">
          <button onClick={this.onTTSRequested}>
            Announce!
          </button>

          <select
            value={this.state.ttsLang}
            onChange={e => this.setState({ ttsLang: e.target.value })}>
            {this.state.ttsLanguages && this.state.ttsLanguages.map(lang =>
              <option key={lang.value} value={lang.value}>{lang.label}</option>
            )}
          </select>

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
              {this.state.speakerList.map(x => <li key={x}>{x}</li>) }
            </ul>
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
                  <th>Time</th>
                  <th>Phrase</th>
                  <th>Lang</th>
                  <th>Vol</th>
                  <th>Link</th>
                </tr>
              </thead>
              <tbody>
                {this.state.announcementHistory.slice().reverse().map((item, idx) => (
                  <tr key={idx}>
                    <td>{new Date(item.timestamp).toLocaleString()}</td>
                    <td>{item.phrase}</td>
                    <td>{item.lang || "default"}</td>
                    <td>{item.volume}</td>
                    <td><a href={item.uri}>🔊</a></td>
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
