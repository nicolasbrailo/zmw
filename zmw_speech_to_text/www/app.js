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
                <div className="entry-head">
                  <span className="entry-title">
                    {entry.source}
                  </span>
                  {entry.file && (
                    <span className="entry-meta">
                      {entry.file}
                    </span>
                  )}
                </div>
                <div className="entry-body">
                  {entry.text || <em className="text-secondary">(empty)</em>}
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
