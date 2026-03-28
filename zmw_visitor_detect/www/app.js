class VisitorDetect extends React.Component {
  static buildProps(api_base_path = '', https_server = '') {
    return {
      key: 'visitor_detect',
      api_base_path,
      https_server,
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      detections: [],
      selectedCrop: null,
    };
    this.fetchDetections = this.fetchDetections.bind(this);
  }

  componentDidMount() {
    this.on_app_became_visible();
  }

  on_app_became_visible() {
    this.fetchDetections();
  }

  fetchDetections() {
    mJsonGet(`${this.props.api_base_path}/detections`, (data) => this.setState({ detections: data }));
  }

  formatTime(epoch) {
    return new Date(epoch * 1000).toLocaleString();
  }

  eventLabel(event) {
    switch (event) {
      case 'visitor_recognized': return 'Known';
      case 'new_visitor_recognized': return 'New visitor';
      case 'new_face_detected': return 'New face';
      case 'person_no_face_detected': return 'No face';
      default: return event;
    }
  }

  eventClass(event) {
    switch (event) {
      case 'visitor_recognized': return 'event-known';
      case 'new_visitor_recognized': return 'event-new-visitor';
      case 'new_face_detected': return 'event-new-face';
      case 'person_no_face_detected': return 'event-no-face';
      default: return '';
    }
  }

  render() {
    const { detections, selectedCrop } = this.state;

    return (
      <div>
        <div className="vd-controls">
          <button onClick={this.fetchDetections}>Refresh</button>
          <small>{detections.length} detection{detections.length !== 1 ? 's' : ''}</small>
        </div>

        {selectedCrop && (
          <div className="vd-lightbox" onClick={() => this.setState({ selectedCrop: null })}>
            <img src={selectedCrop} alt="crop" />
          </div>
        )}

        {detections.length === 0 ? (
          <p>No detections yet</p>
        ) : (
          <div className="vd-grid">
            {detections.slice().reverse().map((d, idx) => (
              <div key={idx} className={`vd-card ${this.eventClass(d.event)}`}>
                <img
                  src={`${this.props.api_base_path}/crops/${d.crop_path.split('/').pop()}`}
                  alt={d.name || 'unknown'}
                  onClick={() => this.setState({
                    selectedCrop: `${this.props.api_base_path}/crops/${d.crop_path.split('/').pop()}`
                  })}
                />
                <div className="vd-info">
                  <strong>{d.name || 'Unknown'}</strong>
                  <span className="vd-event">{this.eventLabel(d.event)}</span>
                  <small>{this.formatTime(d.timestamp)}</small>
                  <small>Confidence: {(d.person_confidence * 100).toFixed(0)}%</small>
                  {d.sightings != null && <small>Sightings: {d.sightings}</small>}
                </div>
              </div>
            ))}
          </div>
        )}

        <style>{`
          .vd-controls {
            display: flex;
            align-items: center;
            gap: 1em;
            margin-bottom: 1em;
          }
          .vd-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 0.8em;
          }
          .vd-card {
            border: 2px solid #333;
            border-radius: 6px;
            overflow: hidden;
            background: #1a1a1a;
          }
          .vd-card img {
            width: 100%;
            aspect-ratio: 3/4;
            object-fit: cover;
            cursor: pointer;
          }
          .vd-info {
            padding: 0.5em;
            display: flex;
            flex-direction: column;
            gap: 0.15em;
          }
          .vd-event {
            font-size: 0.85em;
            opacity: 0.8;
          }
          .event-known { border-color: #2a7; }
          .event-new-visitor { border-color: #e90; }
          .event-new-face { border-color: #48f; }
          .event-no-face { border-color: #666; }
          .vd-lightbox {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.85);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 100;
            cursor: pointer;
          }
          .vd-lightbox img {
            max-width: 90vw;
            max-height: 90vh;
            object-fit: contain;
          }
        `}</style>
      </div>
    );
  }
}
