class VisitorDetect extends React.Component {
  static buildProps(api_base_path = '', https_server = '') {
    return { key: 'visitor_detect', api_base_path, https_server };
  }

  constructor(props) {
    super(props);
    this.state = { detections: [], selectedCrop: null };
    this.fetchDetections = this.fetchDetections.bind(this);
  }

  componentDidMount() { this.on_app_became_visible(); }

  on_app_became_visible() { this.fetchDetections(); }

  fetchDetections() {
    mJsonGet(`${this.props.api_base_path}/detections`, (data) => this.setState({ detections: data }));
  }

  cropUrl(d) {
    return d.crop_path ? `${this.props.api_base_path}/crops/${d.crop_path.split('/').pop()}` : null;
  }

  inputImageUrl(d) {
    return d.input_image_path ? `${this.props.api_base_path}/crops/${d.input_image_path.split('/').pop()}` : null;
  }

  render() {
    const { detections, selectedCrop } = this.state;
    const eventLabels = {
      visitor_recognized: 'Known',
      new_visitor_recognized: 'New visitor',
      new_face_detected: 'New face',
      person_no_face_detected: 'No face',
      no_people_detected: 'No people',
    };

    return (
      <div>
        <button onClick={this.fetchDetections}>Refresh</button>
        <small> {detections.length} detection{detections.length !== 1 ? 's' : ''}</small>

        {selectedCrop && (
          <dialog open onClick={() => this.setState({ selectedCrop: null })}>
            <img src={selectedCrop} alt="crop" style={{maxWidth: '90vw', maxHeight: '90vh'}} />
          </dialog>
        )}

        {detections.length === 0 ? (
          <p>No detections yet</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Crop</th>
                <th>Input</th>
                <th>Name</th>
                <th>Event</th>
                <th>Confidence</th>
                <th>Sightings</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {detections.slice().reverse().map((d, idx) => (
                <tr key={idx} style={d.event === 'no_people_detected' ? {opacity: 0.5} : {}}>
                  <td>
                    {this.cropUrl(d) ? (
                      <img
                        src={this.cropUrl(d)}
                        alt={d.name || 'unknown'}
                        style={{width: '80px', cursor: 'pointer'}}
                        onClick={() => this.setState({ selectedCrop: this.cropUrl(d) })}
                      />
                    ) : '-'}
                  </td>
                  <td>
                    {this.inputImageUrl(d) ? (
                      <img
                        src={this.inputImageUrl(d)}
                        alt="input"
                        style={{width: '80px', cursor: 'pointer'}}
                        onClick={() => this.setState({ selectedCrop: this.inputImageUrl(d) })}
                      />
                    ) : '-'}
                  </td>
                  <td><strong>{d.name || (d.event === 'no_people_detected' ? '-' : 'Unknown')}</strong></td>
                  <td>{eventLabels[d.event] || d.event}</td>
                  <td>{d.person_confidence ? (d.person_confidence * 100).toFixed(0) + '%' : '-'}</td>
                  <td>{d.sightings != null ? d.sightings : '-'}</td>
                  <td>{new Date(d.timestamp * 1000).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
  }
}
