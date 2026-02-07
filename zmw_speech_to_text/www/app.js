class SpeechToText extends React.Component {
  static buildProps() {
    return {
      key: 'SpeechToText',
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      history: null,
    };
    this.fetchHistory = this.fetchHistory.bind(this);
  }

  async componentDidMount() {
    this.fetchHistory();
  }

  on_app_became_visible() {
    this.fetchHistory();
  }

  fetchHistory() {
    mJsonGet('/history', (res) => {
      this.setState({ history: res });
    });
  }

  render() {
    if (!this.state.history) {
      return ( <div className="app-loading">Loading...</div> );
    }

    return (
      <div id="SpeechToTextContainer">
        <h3>
          <img src="/favicon.ico" alt="Speech to text service" />
          Transcription History
        </h3>
        {this.state.history.length === 0 ? (
          <p>No transcriptions yet</p>
        ) : (
          <ul>
            {this.state.history.map((entry, idx) => (
              <li key={idx}>
                <div style={{ marginBottom: '5px' }}>
                  <span style={{ color: '#4a90e2', fontWeight: 'bold' }}>
                    {entry.source}
                  </span>
                  {entry.file && (
                    <span style={{ color: '#888', fontSize: '0.9em', marginLeft: '10px' }}>
                      {entry.file}
                    </span>
                  )}
                </div>
                <div style={{ marginLeft: '20px', fontSize: '0.95em' }}>
                  {entry.text || <em style={{ color: '#888' }}>(empty)</em>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }
}

z2mStartReactApp('#app_root', SpeechToText);
