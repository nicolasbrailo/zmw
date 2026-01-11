class CamViewer extends React.Component {
  static buildProps(api_base_path = '', svc_full_url = '', cam_host = '') {
    return {
      key: `cam_viewer_${cam_host}`,
      api_base_path,
      svc_full_url,
      cam_host,
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      imageTimestamp: Date.now(),
      isLoading: false,
      isRecording: false,
      recordDuration: 20,
      recordingTimeLeft: 0,
      cameras: [],
      selectedCamera: props.cam_host || '',
      camerasLoading: !props.cam_host,
      imageError: false,
    };
    this.countdownInterval = null;

    this.onSnapRequested = this.onSnapRequested.bind(this);
    this.onRecordRequested = this.onRecordRequested.bind(this);
    this.onCameraSelected = this.onCameraSelected.bind(this);
    this.onImageError = this.onImageError.bind(this);
  }

  componentDidMount() {
    if (!this.props.cam_host) {
      this.fetchCameras();
    }
  }

  fetchCameras() {
    mJsonGet(`${this.props.api_base_path}/ls_cams`,
      (cameras) => {
        this.setState({
          cameras: cameras,
          camerasLoading: false,
          selectedCamera: cameras.length > 0 ? cameras[0] : '',
        });
      },
      (err) => {
        showGlobalError("Failed to fetch cameras: " + err);
        this.setState({ camerasLoading: false });
      });
  }

  onCameraSelected(e) {
    this.setState({
      selectedCamera: e.target.value,
      imageTimestamp: Date.now(),
      imageError: false,
    });
  }

  onImageError() {
    this.setState({ imageError: true });
  }

  on_app_became_visible() {
    // We can request a snap to refresh state, but this is unlikely to be the behaviour the user wants. It's more
    // likely that the user wants to see the last time the snap was updated due to motion. If the user does want
    // to trigger an update, they can do it manually.
    // this.onSnapRequested();
  }

  onSnapRequested() {
    this.setState({ isLoading: true });
    const cam_host = this.state.selectedCamera || this.props.cam_host;

    mTextGet(`${this.props.api_base_path}/snap/${cam_host}`,
      () => {
        console.log("Snapshot captured");
        // Refresh the image by updating timestamp
        setTimeout(() => {
          console.log("Refresh img");
          this.setState({
            imageTimestamp: Date.now(),
            isLoading: false,
            imageError: false,
          });
        }, 500); // Small delay to ensure snapshot is saved
      },
      (err) => {
        showGlobalError("Failed to capture snapshot: " + err);
        this.setState({ isLoading: false });
      });
  }

  onRecordRequested() {
    const secs = this.state.recordDuration;
    const cam_host = this.state.selectedCamera || this.props.cam_host;
    this.setState({ isRecording: true, recordingTimeLeft: secs });

    mTextGet(`${this.props.api_base_path}/record/${cam_host}?secs=${secs}`,
      () => {
        console.log(`Recording started for ${secs} seconds`);
        this.countdownInterval = setInterval(() => {
          this.setState((prevState) => {
            const newTime = prevState.recordingTimeLeft - 1;
            if (newTime <= 0) {
              clearInterval(this.countdownInterval);
              return { isRecording: false, recordingTimeLeft: 0 };
            }
            return { recordingTimeLeft: newTime };
          });
        }, 1000);
      },
      (err) => {
        showGlobalError("Failed to start recording: " + err.response);
        this.setState({ isRecording: false, recordingTimeLeft: 0 });
      });
  }

  render() {
    const { api_base_path, svc_full_url } = this.props;
    const { selectedCamera, cameras, camerasLoading, imageError } = this.state;
    const cam_host = selectedCamera || this.props.cam_host;
    const lastSnapUrl = cam_host ? `${api_base_path}/lastsnap/${cam_host}?t=${this.state.imageTimestamp}` : '';
    const imgSrc = imageError ? `${api_base_path}/no-snap.png` : lastSnapUrl;
    const showCameraSelector = !this.props.cam_host && cameras.length > 0;

    if (camerasLoading) {
      return (
        <section id="zwm_reolink_doorcam">
          <p>Loading cameras...</p>
        </section>
      );
    }

    if (!cam_host) {
      return (
        <section id="zwm_reolink_doorcam">
          <p>No cameras available</p>
        </section>
      );
    }

    return (
      <section id="zwm_reolink_doorcam">
        {showCameraSelector && (
          <div>
            <label>Camera: </label>
            <select value={selectedCamera} onChange={this.onCameraSelected}>
              {cameras.map(cam => (
                <option key={cam} value={cam}>{cam}</option>
              ))}
            </select>
          </div>
        )}
        <div>
          <button onClick={this.onSnapRequested} disabled={this.state.isLoading || this.state.isRecording}>
            {this.state.isLoading ? "Capturing..." : "Take New Snapshot"}
          </button>
          <button onClick={this.onRecordRequested} disabled={this.state.isRecording || this.state.isLoading}>
            {this.state.isRecording ? `Recording (${this.state.recordingTimeLeft}s)...` : `Record Video (${this.state.recordDuration}s)`}
          </button>
          <button onClick={() => window.location.href=`${svc_full_url}/nvr`}>View Recordings</button>
          <input
            type="range"
            min="10"
            max="100"
            value={this.state.recordDuration}
            onChange={(e) => this.setState({ recordDuration: parseInt(e.target.value) })}
            disabled={this.state.isRecording}
          />
        </div>

        <a href={lastSnapUrl}>
        <img
          className="img-always-on-screen quite-round"
          src={imgSrc}
          alt={`Last snap from ${cam_host}`}
          onError={this.onImageError}
        /></a>
      </section>
    );
  }
}

function NVRViewer(props) {
  const [cameras, setCameras] = React.useState([]);
  const [selectedCam, setSelectedCam] = React.useState(null);
  const [recordings, setRecordings] = React.useState([]);
  const [snapshots, setSnapshots] = React.useState([]);
  const [days, setDays] = React.useState(3);
  const [isLoading, setIsLoading] = React.useState(true);

  React.useEffect(() => {
    // Fetch list of cameras on component mount
    mJsonGet(`${props.api_base_path}/nvr/api/cameras`, (cams) => {
      console.log(cams)
        setCameras(cams.cameras);
        if (cams.cameras.length > 0) {
          setSelectedCam(cams.cameras[0]);
        }
        setIsLoading(false);
      }
    );
  }, []);

  React.useEffect(() => {
    // Fetch recordings and snapshots when camera or days changes
    if (!selectedCam) return;

    setIsLoading(true);

    // Fetch recordings
    mJsonGet(`${props.api_base_path}/nvr/api/${selectedCam}/recordings?days=${days}`,
      (data) => {
        setRecordings(data.recordings);
        setIsLoading(false);
      },
      (err) => {
        setIsLoading(false);
      }
    );

    // Fetch snapshots
    mJsonGet(`${props.api_base_path}/nvr/api/${selectedCam}/snapshots`,
      (data) => {
        setSnapshots(data.snapshots || []);
      },
      (err) => {
        setSnapshots([]);
      }
    );
  }, [selectedCam, days]);

  const formatFilename = (filename) => {
    try {
      const dateStr = filename.split('.')[0];
      const hour = dateStr.split('_')[1];
      const month = parseInt(dateStr.substring(4, 6));
      const day = parseInt(dateStr.substring(6, 8));
      const hr = parseInt(hour.substring(0, 2));
      const minute = parseInt(hour.substring(2, 4));
      const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      const monthName = monthNames[month - 1] || `Month ${month}`;
      return `${monthName} - ${day.toString().padStart(2, '0')} - ${hr.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`;
    } catch (e) {
      return filename;
    }
  };

  const formatSnapshotFilename = (filename) => {
    try {
      // Expected format: snap_YYYYMMDD_HHMMSS.jpg
      const dateStr = filename.replace('snap_', '').split('.')[0];
      const parts = dateStr.split('_');
      const datePart = parts[0];
      const timePart = parts[1];
      const month = parseInt(datePart.substring(4, 6));
      const day = parseInt(datePart.substring(6, 8));
      const hr = parseInt(timePart.substring(0, 2));
      const minute = parseInt(timePart.substring(2, 4));
      const sec = parseInt(timePart.substring(4, 6));
      const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      const monthName = monthNames[month - 1] || `Month ${month}`;
      return `${monthName} ${day} - ${hr.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
    } catch (e) {
      return filename;
    }
  };

  if (isLoading && cameras.length === 0) {
    return (<div className="card hint">
            <p>Loading cameras!</p>
            <p>Please wait...</p>
            </div>)
  }

  return (
    <section id="zmw_reolink_nvr">
      <details open>
      <summary>Config</summary>
        {cameras.length > 1 && (
          <select
            value={selectedCam || ''}
            onChange={e => setSelectedCam(e.target.value)}
          >
            {cameras.map(cam => (
              <option key={cam} value={cam}>{cam}</option>
            ))}
          </select>
        )}

        <select
          value={days}
          onChange={e => setDays(parseInt(e.target.value))}
        >
          <option value="1">Last 1 day</option>
          <option value="3">Last 3 days</option>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
          <option value="0">All recordings</option>
        </select>

        <button onClick={() => window.location.href = '/'}>← Back to Camera</button>
      </details>

      {isLoading ? (
        <p>Loading...</p>
      ) : (
        <>
          {snapshots.length > 0 && (
            <details open>
              <summary>Recent Snapshots ({snapshots.length})</summary>
              <div className="gallery snapshots">
                {snapshots.map((snap, idx) => (
                  <figure key={idx}>
                    <a href={snap.url} target="_blank">
                      <img src={snap.url} alt={snap.filename}/>
                      <figcaption>
                        {formatSnapshotFilename(snap.filename)}
                      </figcaption>
                    </a>
                  </figure>
                ))}
              </div>
            </details>
          )}

          <details open>
            <summary>Recordings ({recordings.length})</summary>
            {recordings.length === 0 ? (
              <p>No recordings found for the selected period</p>
            ) : (
              <div className="gallery">
                {recordings.map((rec, idx) => (
                  <figure key={idx}>
                    <a href={rec.video_url} target="_blank">
                      <img src={rec.thumbnail_url || 'thumbnail-gen-failed'} alt={rec.filename}/>
                      <figcaption>
                        {formatFilename(rec.filename)} ({rec.size})
                      </figcaption>
                    </a>
                  </figure>
                ))}
              </div>
            )}
          </details>
        </>
      )}
    </section>
  );
}
