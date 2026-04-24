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
      loading: true,
    };
    this.refresh = this.refresh.bind(this);
    this._timer = null;
  }

  componentDidMount() {
    this.on_app_became_visible();
    this._timer = setInterval(this.refresh, 5000);
  }

  componentWillUnmount() {
    if (this._timer) clearInterval(this._timer);
  }

  on_app_became_visible() {
    this.refresh();
  }

  refresh() {
    mJsonGet('/get_homeboards_state', (data) => {
      const homeboards = (data && data.homeboards) || [];
      this.setState({ homeboards, loading: false });
    }, () => {
      this.setState({ loading: false });
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

  renderDisplayedPhoto(photo) {
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
          {photo.filename && (
            <>
              <dt>File</dt>
              <dd>
                {photo.src_url
                  ? (<a href={photo.src_url} target="_blank" rel="noreferrer">{photo.filename}</a>)
                  : photo.filename}
              </dd>
            </>
          )}
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

  renderHomeboard(hb) {
    const online = hb.state === 'online';
    const slideshowActive = !!hb.slideshow_active;
    return (
      <div key={hb.id} className={online ? 'card' : 'card warn'}>
        <h3>{hb.id}</h3>
        <div>
          Bridge: <strong>{hb.state}</strong>
          {online && (<> — Slideshow: <strong>{slideshowActive ? 'Active' : 'Not active'}</strong></>)}
        </div>
        {this.renderOccupancy(hb.occupancy)}
        {hb.displayed_photo && (
          <>
            <h4>Now showing</h4>
            {this.renderDisplayedPhoto(hb.displayed_photo)}
          </>
        )}
      </div>
    );
  }

  render() {
    const { homeboards, loading } = this.state;
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
    return (
      <div>
        <div>{homeboards.length} homeboard(s) known</div>
        {homeboards.map((hb) => this.renderHomeboard(hb))}
      </div>
    );
  }
}
