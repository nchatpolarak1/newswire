import Link from 'next/link';

export default function Navbar() {
    return (
        <nav>
            <div className="nav-div">
                <Link href="/">
                    <span id="navbar-home-span-wrapper">
                        <span id="navbar-home-span">Newswire</span>
                    </span>
                </Link>
                <div className="navbar-navigation-wrapper" id="navbar-default">
                    <div className="navbar-list-wrapper">
                        <ul className="navbar-list">
                            <li>
                                <Link href="/"><span className="menu-item" aria-current="page">Feed</span></Link>
                            </li>
                            <li>
                                <Link href="/pipeline"><span className="menu-item">Pipeline</span></Link>
                            </li>
                            <li>
                                <p id="nav-divider">|</p>
                            </li>
                            <li>
                                <Link href="https://github.com/nchatpolarak1/newswire" target="_blank">
                                    <span className="menu-item">GitHub</span>
                                </Link>
                            </li>
                        </ul>
                    </div>
                </div>
            </div>
        </nav>
    );
}
