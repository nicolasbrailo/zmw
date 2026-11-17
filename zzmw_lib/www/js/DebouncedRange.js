class DebouncedRange extends React.Component {
  // "Smart" range that will let you update the UI, but will only fire a change event once the user
  // releases the element. This is to avoid spamming changes that may need to travel over the network
  constructor(props) {
    super(props);
    this.state = {
      changing: false,
      value: props.value ?? props.min ?? 0,
    };
  }

  componentDidUpdate(prevProps) {
    if (prevProps.value !== this.props.value && !this.state.changing) {
      this.setState({ value: this.props.value ?? 0 });
    }
  }

  onChange(value) {
    this.setState({ value: value });
  }

  onMouseUp(_) {
    this.setState({ changing: false });
    this.props.onChange({ target: { value: this.state.value } });
  }

  onMouseDown(_) {
    this.setState({ changing: true });
  }

  render() {
    return (
      <input
        type="range"
        onChange={(e) => this.onChange(e.target.value)}
        onMouseUp={(e) => this.onMouseUp(e.target.value)}
        onMouseDown={(e) => this.onMouseDown(e.target.value)}
        onTouchStart={(e) => this.onMouseDown(e.target.value)}
        onTouchEnd={(e) => this.onMouseUp(e.target.value)}
        className={this.props.className}
        disabled={this.props.disabled}
        min={this.props.min}
        max={this.props.max}
        value={this.state.value}
      />
    );
  }
}
