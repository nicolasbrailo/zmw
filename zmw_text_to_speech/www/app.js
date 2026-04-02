class TextToSpeech extends React.Component {
  static buildProps() {
    return {
      key: 'TextToSpeech',
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      text: '',
      voices: null,
      selectedVoice: '',
      fuzzy: false,
      history: null,
      synthesizing: false,
    };
    this.onSynthesize = this.onSynthesize.bind(this);
    this.fetchHistory = this.fetchHistory.bind(this);
    this.fetchVoices = this.fetchVoices.bind(this);
  }

  componentDidMount() {
    this.on_app_became_visible();
  }

  on_app_became_visible() {
    this.fetchVoices();
    this.fetchHistory();
  }

  fetchVoices() {
    mJsonGet('/voices', (data) => {
      this.setState({ voices: data });
      if (data && data.length > 0 && !this.state.selectedVoice) {
        const dflt = data.find(v => v.default_fallback);
        this.setState({ selectedVoice: dflt ? dflt.voice_id : data[0].voice_id });
      }
    });
  }

  fetchHistory() {
    mJsonGet('/tts_history', (data) => this.setState({ history: data }));
  }

  onSynthesize() {
    const text = this.state.text.trim();
    if (!text) return;

    this.setState({ synthesizing: true });
    mJsonPut('/synthesize', {
      text: text,
      speaker: this.state.selectedVoice,
      fuzzy: this.state.fuzzy,
    }, () => {
      this.setState({ text: '' });
      this._pollForNewHistory();
    }, (err) => {
      this.setState({ synthesizing: false });
    });
  }

  _pollForNewHistory() {
    const prevLen = this.state.history ? this.state.history.length : 0;
    let attempts = 0;
    const poll = () => {
      mJsonGet('/tts_history', (data) => {
        if (data.length > prevLen) {
          this.setState({ history: data, synthesizing: false });
        } else if (attempts < 30) {
          attempts++;
          setTimeout(poll, 1000);
        } else {
          this.setState({ history: data, synthesizing: false });
        }
      });
    };
    setTimeout(poll, 1000);
  }

  formatVoiceLabel(v) {
    let label = `${v.name} (${v.locale}, ${v.quality})`;
    if (v.default_for) label += ` [default: ${v.default_for.join(', ')}]`;
    if (v.fuzzy) label += ' *fuzzy*';
    return label;
  }

  render() {
    if (!this.state.voices || !this.state.history) {
      return (<div className="app-loading">Loading...</div>);
    }

    const selectedVoiceInfo = this.state.voices.find(v => v.voice_id === this.state.selectedVoice);
    const canFuzzy = selectedVoiceInfo && selectedVoiceInfo.fuzzy;

    return (
      <div>
        <h3>
          <img src="/favicon.ico" alt="Text to Speech" />
          Text to Speech
        </h3>

        <fieldset>
          <legend>Generate Speech</legend>
          <textarea
            rows="3"
            placeholder="Text to synthesize..."
            value={this.state.text}
            onChange={e => this.setState({ text: e.target.value })}
            onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) this.onSynthesize(); }}
          />

          <div className="ctrl-box-with-range">
            <select
              value={this.state.selectedVoice}
              onChange={e => this.setState({ selectedVoice: e.target.value })}>
              {this.state.voices.map(v =>
                <option key={v.voice_id} value={v.voice_id}>{this.formatVoiceLabel(v)}</option>
              )}
            </select>

            <label>
              <input
                type="checkbox"
                checked={this.state.fuzzy}
                onChange={e => this.setState({ fuzzy: e.target.checked })}
              />
              Fuzzy{canFuzzy ? '' : ' (n/a for this voice)'}
            </label>

            <button
              onClick={this.onSynthesize}
              disabled={this.state.synthesizing || !this.state.text.trim()}>
              {this.state.synthesizing ? 'Generating...' : 'Synthesize'}
            </button>
          </div>
        </fieldset>

        <h4>History ({this.state.history.length})</h4>
        {this.state.history.length === 0 ? (
          <p>No synthesis requests yet</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Text</th>
                <th>Voice</th>
                <th>Fuzzy</th>
                <th>MP3</th>
              </tr>
            </thead>
            <tbody>
              {this.state.history.slice().reverse().map((item, idx) => (
                <tr key={idx}>
                  <td>{new Date(item.timestamp).toLocaleString()}</td>
                  <td>
                    {item.text}
                    {item.original_text && item.text !== item.original_text &&
                      <div><small><em>Original: {item.original_text}</em></small></div>
                    }
                  </td>
                  <td>{item.voice_id}</td>
                  <td>{item.fuzzy ? 'Yes' : 'No'}</td>
                  <td>{item.mp3_url
                    ? <audio controls preload="none" src={item.mp3_url}></audio>
                    : '-'
                  }</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
  }
}
