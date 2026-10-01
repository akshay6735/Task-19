import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useCart } from '../context/CartContext'
import { useWishlist } from '../context/WishlistContext'
import { useTheme } from '../context/ThemeContext'
import Avatar from './Avatar'
import NotificationBell from './NotificationBell'

const NEXT_THEME = { light: 'dark', dark: 'sepia', sepia: 'light' }
const THEME_ICON = { light: '🌙', dark: '📜', sepia: '☀️' } // icon shown = the theme you'll switch TO

export default function Navbar() {
  const { user, isAdmin, logout } = useAuth()
  const { cartCount } = useCart()
  const { wishlist } = useWishlist()
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/')
  }

  return (
    <nav className="navbar">
      <Link to="/" className="navbar-brand">🛍️ ShopEasy</Link>

      <div className="navbar-links">
        <Link to="/">Home</Link>

        {user && !isAdmin && <Link to="/orders">My Orders</Link>}
        {user && <Link to="/profile">My Profile</Link>}
        {user && !isAdmin && (
          <Link to="/wishlist" className="navbar-wishlist">
            Wishlist
            {wishlist.length > 0 && <span className="cart-badge">{wishlist.length}</span>}
          </Link>
        )}

        {isAdmin && (
          <>
            <Link to="/admin">Dashboard</Link>
            <Link to="/admin/products">Manage Products</Link>
            <Link to="/admin/orders">All Orders</Link>
            <Link to="/admin/coupons">Coupons</Link>
          </>
        )}

        <Link to="/cart" className="navbar-cart">
          Cart
          {cartCount > 0 && <span className="cart-badge">{cartCount}</span>}
        </Link>

        <button
          className="theme-toggle-btn"
          onClick={toggleTheme}
          aria-label="Cycle theme"
          title={`Switch to ${NEXT_THEME[theme]} mode`}
        >
          {THEME_ICON[theme]}
        </button>

        {user && <NotificationBell />}

        {user ? (
          <div className="navbar-user">
            <Link to="/profile" className="navbar-profile" title="My Profile">
              <Avatar name={user.name} avatarUrl={user.avatar_url} size={32} />
              <span>{user.name}</span>
            </Link>
            <button className="btn btn-link" onClick={handleLogout}>Logout</button>
          </div>
        ) : (
          <>
            <Link to="/login">Login</Link>
            <Link to="/register">Register</Link>
          </>
        )}
      </div>
    </nav>
  )
}
