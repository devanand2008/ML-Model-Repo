import { Component,type ReactNode } from 'react';
import { Link,useLocation } from 'react-router-dom';

class Boundary extends Component<{children:ReactNode;resetKey:string},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidUpdate(previous:{resetKey:string}){if(previous.resetKey!==this.props.resetKey&&this.state.failed)this.setState({failed:false});}
  render(){
    if(!this.state.failed)return this.props.children;
    return <main className="to-page" role="alert"><h1>This module could not open</h1><p>Reload this page to try again, or open another part of the app.</p><div className="ml-actions"><button className="to-button primary" onClick={()=>window.location.reload()}>Reload page</button><Link className="to-button" to="/">App home</Link><Link className="to-button" to="/status">Check app readiness</Link></div></main>;
  }
}
export default function ModuleErrorBoundary({children}:{children:ReactNode}){const location=useLocation();return <Boundary resetKey={location.pathname}>{children}</Boundary>;}
