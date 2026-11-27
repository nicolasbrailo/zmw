class WhatsAppMonitor extends React.Component {
  static buildProps() {
    return {
      key: 'WhatsAppMonitor',
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      messages: null,
    };
    this.fetchMessages = this.fetchMessages.bind(this);
  }

  async componentDidMount() {
    this.fetchMessages();
  }

  on_app_became_visible() {
    this.fetchMessages();
  }

  fetchMessages() {
    mJsonGet('/messages', (res) => {
      this.setState({ messages: res });
    });
  }

  formatTimestamp(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString();
  }

  render() {
    if (!this.state.messages) {
      return ( <div className="app-loading">Loading...</div> );
    }

    return (
      <div id="WhatsAppMonitorContainer">
        <h3>
          <img src="/favicon.ico" alt="WhatsappMqtt service" />
          WhatsApp Messages History
        </h3>
        {this.state.messages.length === 0 ? (
          <p>No messages yet</p>
        ) : (
          <ul>
            {this.state.messages.map((msg, idx) => this.renderMessage(msg, idx))}
          </ul>
        )}
      </div>
    )
  }

  renderMessage(msg, idx) {

    let messageContent = '';
    let statusBadge = null;

    if (msg.type === 'text') {
      messageContent = msg.text || '';
      if (msg.status === 'not_implemented') {
        statusBadge = <span className="text-small text-error">[NOT IMPLEMENTED]</span>;
      }
    } else if (msg.type === 'photo') {
      messageContent = `📷 Photo: ${msg.path}`;
      if (msg.caption) {
        messageContent += ` (${msg.caption})`;
      }
    }

    return (
      <li key={idx}>
        <div className="entry-head">
          <span className="entry-title">
            → Sent
          </span>
          <span className="entry-meta">
            {this.formatTimestamp(msg.timestamp)}
          </span>
          {statusBadge}
        </div>
        <div className="entry-body">
          {messageContent}
        </div>
      </li>
    );
  }
}

z2mStartReactApp('#app_root', WhatsAppMonitor);
