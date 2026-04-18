class Homeboard extends React.Component {
  static buildProps() {
    return {
      key: 'Homeboard',
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      homeboards: [],
      selected: null,
      loading: true,
      transitionSecs: 30,
      embedQr: false,
      width: 1024,
      height: 768,
      displayedPhoto: null,
    };
    this.onNext = this.onNext.bind(this);
    this.onPrev = this.onPrev.bind(this);
    this.onForceOn = this.onForceOn.bind(this);
    this.onForceOff = this.onForceOff.bind(this);
    this.onSubmitTransition = this.onSubmitTransition.bind(this);
    this.onSubmitEmbedQr = this.onSubmitEmbedQr.bind(this);
    this.onSubmitTargetSize = this.onSubmitTargetSize.bind(this);
    this.onSelect = this.onSelect.bind(this);
    this.refresh = this.refresh.bind(this);
    this.refreshPhoto = this.refreshPhoto.bind(this);
    this._photoTimer = null;
  }

  componentDidMount() {
    this.on_app_became_visible();
    this._photoTimer = setInterval(this.refreshPhoto, 10000);
  }

  componentWillUnmount() {
    if (this._photoTimer) clearInterval(this._photoTimer);
  }

  componentDidUpdate(_prevProps, prevState) {
    if (prevState.selected !== this.state.selected) {
      this.refreshPhoto();
    }
  }

  on_app_became_visible() {
    this.refresh();
    this.refreshPhoto();
  }

  refresh() {
    mJsonGet('/list', (data) => {
      const homeboards = (data && data.homeboards) || [];
      this.setState((prev) => {
        let selected = prev.selected;
        const ids = homeboards.map((h) => h.id);
        if (selected && !ids.includes(selected)) selected = null;
        if (!selected && ids.length > 0) selected = ids[0];
        return { homeboards, selected, loading: false };
      });
    }, () => {
      this.setState({ loading: false });
    });
  }

  refreshPhoto() {
    const hb = this.state.selected;
    const selectedHb = (this.state.homeboards || []).find((h) => h.id === hb);
    if (!hb || !selectedHb || selectedHb.state !== 'online' || !selectedHb.slideshow_active) {
      this.setState({ displayedPhoto: null });
      return;
    }
    const url = `/displayed_photo?homeboard_id=${encodeURIComponent(hb)}`;
    mJsonGet(url, (data) => {
      this.setState({ displayedPhoto: (data && data.displayed_photo) || null });
    }, () => {});
  }

  onSelect(e) {
    this.setState({ selected: e.target.value });
  }

  _send(url, extra) {
    const hb = this.state.selected;
    if (!hb) return;
    const body = { homeboard_id: hb, ...(extra || {}) };
    mJsonPut(url, body, () => {
      setTimeout(this.refreshPhoto, 500);
    }, () => {
      this.setState({});
    });
  }

  onPrev() { this._send('/prev'); }
  onNext() { this._send('/next'); }
  onForceOn() { this._send('/force_on'); }
  onForceOff() { this._send('/force_off'); }

  onSubmitTransition() {
    this._send('/set_transition_time_secs', { secs: Number(this.state.transitionSecs) });
  }

  onSubmitEmbedQr() {
    this._send('/set_embed_qr', { enabled: !!this.state.embedQr });
  }

  onSubmitTargetSize() {
    this._send('/set_target_size', {
      width: Number(this.state.width),
      height: Number(this.state.height),
    });
  }

  renderOccupancy(occ) {
    if (!occ) {
      return (<div>Occupancy: <em>unknown</em></div>);
    }
    const state = occ.occupied ? 'Occupied' : 'Empty';
    const distance = (typeof occ.distance_cm === 'number')
      ? `${occ.distance_cm} cm`
      : 'unknown';
    const ago = (typeof occ.ts === 'number')
      ? ` (${Math.max(0, Math.round(Date.now() / 1000 - occ.ts))}s ago)`
      : '';
    return (
      <div>
        Occupancy: <strong>{state}</strong> — distance {distance}{ago}
      </div>
    );
  }

  renderDisplayedPhoto() {
    const photo = this.state.displayedPhoto;
    if (!photo) {
      return (<p>No photo info available.</p>);
    }
    const camera = [photo['Image Make'], photo['Image Model']].filter(Boolean).join(' ');
    const w = photo['EXIF ExifImageWidth'];
    const h = photo['EXIF ExifImageLength'];
    const size = (w && h) ? `${w} x ${h}` : null;
    const taken = photo['EXIF DateTimeOriginal'];
    const geo = photo.reverse_geo || {};
    const location = geo.revgeo || [geo.city, geo.state, geo.country].filter(Boolean).join(', ');
    const gps = photo.gps;
    const mapUrl = (gps && gps.lat != null && gps.lon != null)
      ? `https://www.openstreetmap.org/?mlat=${gps.lat}&mlon=${gps.lon}#map=16/${gps.lat}/${gps.lon}`
      : null;
    return (
      <div>
        <dl>
          {photo.albumname && (<><dt>Album</dt><dd>{photo.albumname}</dd></>)}
          {photo.filename && (<><dt>File</dt><dd><a href={photo.src_url}>{photo.filename}</a></dd></>)}
          {taken && (<><dt>Taken</dt><dd>{taken}</dd></>)}
          {camera && (<><dt>Camera</dt><dd>{camera}</dd></>)}
          {size && (<><dt>Size</dt><dd>{size}</dd></>)}
          {location && (
            <>
              <dt>Location</dt>
              <dd>
                {mapUrl
                  ? (<a href={mapUrl} target="_blank" rel="noreferrer">{location}</a>)
                  : location}
              </dd>
            </>
          )}
        </dl>
        <details>
          <summary>Raw metadata</summary>
          <pre>{JSON.stringify(photo, null, 2)}</pre>
        </details>
      </div>
    );
  }

  render() {
    const { homeboards, selected, loading, transitionSecs, embedQr, width, height } = this.state;
    if (loading) {
      return (<div>Loading...</div>);
    }
    if (homeboards.length === 0) {
      return (
        <div>
          <p>No homeboards discovered yet.</p>
          <button onClick={this.refresh}>Refresh</button>
        </div>
      );
    }
    const selectedHb = homeboards.find((h) => h.id === selected);
    const isOnline = !!selectedHb && selectedHb.state === 'online';
    const slideshowActive = !!(selectedHb && selectedHb.slideshow_active);
    const disabled = !isOnline;
    return (
      <div>
        <div>
          <label>
            Homeboard:
            <select value={selected || ''} onChange={this.onSelect}>
              {homeboards.map((hb) => (
                <option key={hb.id} value={hb.id}>
                  {hb.id} ({hb.state})
                </option>
              ))}
            </select>
          </label>
          <button onClick={this.refresh}>Refresh</button>
        </div>

        {!isOnline && (
          <div className="card warn">
            <p><strong>{selected}</strong> is offline.</p>
          </div>
        )}

        {isOnline && (
          <>
            <div>
              Slideshow: <strong>({slideshowActive ? 'Active' : 'Not active'})</strong>
            </div>

            {this.renderOccupancy(selectedHb && selectedHb.occupancy)}

            <div>
              <button onClick={this.onPrev} disabled={disabled}>Prev</button>
              <button onClick={this.onNext} disabled={disabled}>Next</button>
              <button onClick={this.onForceOn} disabled={disabled}>Force On</button>
              <button onClick={this.onForceOff} disabled={disabled}>Force Off</button>
            </div>

            {slideshowActive && (
              <div className="card">
                <h3>Now showing</h3>
                {this.renderDisplayedPhoto()}
              </div>
            )}

            <details>
              <summary>Config</summary>

              <div>
                <label>
                  Transition time (secs):
                  <input
                    type="number"
                    min="0"
                    value={transitionSecs}
                    onChange={(e) => this.setState({ transitionSecs: e.target.value })}
                  />
                </label>
                <button onClick={this.onSubmitTransition} disabled={disabled}>Apply</button>
              </div>

              <div>
                <label>
                  Embed QR:
                  <input
                    type="checkbox"
                    checked={embedQr}
                    onChange={(e) => this.setState({ embedQr: e.target.checked })}
                  />
                </label>
                <button onClick={this.onSubmitEmbedQr} disabled={disabled}>Apply</button>
              </div>

              <div>
                <label>
                  Target size:
                  <input
                    type="number"
                    min="1"
                    value={width}
                    onChange={(e) => this.setState({ width: e.target.value })}
                  />
                  x
                  <input
                    type="number"
                    min="1"
                    value={height}
                    onChange={(e) => this.setState({ height: e.target.value })}
                  />
                </label>
                <button onClick={this.onSubmitTargetSize} disabled={disabled}>Apply</button>
              </div>
            </details>
          </>
        )}
      </div>
    );
  }
}
