import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { useForm } from '../hooks/useForm'
import Avatar from '../components/Avatar'
import ConfirmModal from '../components/ConfirmModal'

const MAX_AVATAR_BYTES = 2 * 1024 * 1024 // matches the backend's 2 MB limit
const ALLOWED_TYPES = ['image/png', 'image/jpeg', 'image/webp']

// ---------- frontend validation (runs before anything is sent) ----------
function validateProfile(values) {
  const errors = {}
  if (!values.name.trim()) errors.name = 'Name is required'
  if (!values.email.trim()) errors.email = 'Email is required'
  else if (!/^\S+@\S+\.\S+$/.test(values.email.trim())) errors.email = 'Enter a valid email address'
  return errors
}

function validatePassword(values) {
  const errors = {}
  if (!values.current_password) errors.current_password = 'Enter your current password'
  if (values.new_password.length < 6) errors.new_password = 'Must be at least 6 characters'
  if (values.confirm_password !== values.new_password) errors.confirm_password = 'Passwords do not match'
  return errors
}

// "2025-01-15" -> "Jan 2025". Built from parts (not new Date("2025-01-15"))
// so timezones can't shift the date to the previous/next month.
function formatMemberSince(isoDate) {
  if (!isoDate) return ''
  const [y, m] = isoDate.split('-').map(Number)
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short',
  })
}

// A simple 5-point score: the length requirement, a longer length bonus,
// mixed case, a digit, and a symbol. Purely a helpful nudge for the user -
// the backend's only real rule is the 6-character minimum.
function getPasswordStrength(password) {
  if (!password) return { percent: 0, label: '', level: '' }
  if (password.length < 6) return { percent: 12, label: 'Too short', level: 'weak' }

  let score = 1 // meets the minimum length
  if (password.length >= 10) score++
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++
  if (/\d/.test(password)) score++
  if (/[^A-Za-z0-9]/.test(password)) score++

  const byScore = {
    1: { label: 'Weak', level: 'weak' },
    2: { label: 'Fair', level: 'fair' },
    3: { label: 'Good', level: 'good' },
    4: { label: 'Strong', level: 'strong' },
    5: { label: 'Very Strong', level: 'strong' },
  }
  return { percent: (score / 5) * 100, ...byScore[score] }
}

function PasswordStrengthMeter({ password }) {
  const { percent, label, level } = getPasswordStrength(password)
  if (!password) return null
  return (
    <div className="password-strength" aria-live="polite">
      <div className="password-strength-track">
        <div className={`password-strength-fill password-strength-${level}`} style={{ width: `${percent}%` }} />
      </div>
      <span className={`password-strength-label password-strength-label-${level}`}>{label}</span>
    </div>
  )
}

function Field({ label, name, type = 'text', value, onChange, error, autoComplete }) {
  return (
    <div className="form-field">
      <label htmlFor={name}>{label}</label>
      <input
        id={name}
        name={name}
        type={type}
        value={value}
        onChange={onChange}
        autoComplete={autoComplete}
        aria-invalid={error ? 'true' : 'false'}
        aria-describedby={error ? `${name}-error` : undefined}
        className={error ? 'input-error' : ''}
      />
      {error && <p id={`${name}-error`} className="field-error" role="alert">{error}</p>}
    </div>
  )
}

export default function ProfilePage() {
  const { user, updateUser, logout } = useAuth()
  const { showToast } = useToast()
  const navigate = useNavigate()

  const [profile, setProfile] = useState(null) // full record from GET /api/me
  const [loadError, setLoadError] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  // ---------- activity summary ----------
  const [stats, setStats] = useState(null)
  const [statsError, setStatsError] = useState('')

  // ---------- delete account ----------
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const profileForm = useForm({ name: '', email: '' }, validateProfile)
  const passwordForm = useForm(
    { current_password: '', new_password: '', confirm_password: '' },
    validatePassword
  )
  const setProfileValues = profileForm.setValues // stable (it's a useState setter)

  // ---------- load the current profile ----------
  useEffect(() => {
    let cancelled = false
    setLoadError('')
    api.get('/me')
      .then(res => {
        if (cancelled) return
        setProfile(res.data)
        setProfileValues({ name: res.data.name, email: res.data.email })
        updateUser(res.data)
      })
      .catch(() => {
        if (!cancelled) setLoadError('Could not load your profile. Please try again.')
      })
    return () => { cancelled = true }
  }, [reloadKey, setProfileValues, updateUser])

  useEffect(() => {
    let cancelled = false
    api.get('/me/stats')
      .then(res => { if (!cancelled) setStats(res.data) })
      .catch(() => { if (!cancelled) setStatsError('Could not load your activity summary.') })
    return () => { cancelled = true }
  }, [])

  // ---------- delete account ----------
  async function handleDeleteAccount() {
    setDeleting(true)
    try {
      await api.delete('/me')
      await logout()
      navigate('/')
    } catch (err) {
      setShowDeleteModal(false)
      showToast(err.response?.data?.error || 'Could not delete your account. Try again.', 'error')
    } finally {
      setDeleting(false)
    }
  }

  // ---------- Section 1: profile picture ----------
  const fileInputRef = useRef(null)
  const [avatarFile, setAvatarFile] = useState(null)
  const [avatarPreview, setAvatarPreview] = useState(null)
  const [avatarError, setAvatarError] = useState('')
  const [uploading, setUploading] = useState(false)

  // free the browser memory behind a preview URL when it's replaced or the page closes
  useEffect(() => {
    return () => { if (avatarPreview) URL.revokeObjectURL(avatarPreview) }
  }, [avatarPreview])

  function handleFileChange(e) {
    const file = e.target.files[0]
    e.target.value = '' // lets the user pick the same file again later
    if (!file) return

    setAvatarError('')
    if (!ALLOWED_TYPES.includes(file.type)) {
      setAvatarError('Please choose a PNG, JPG or WEBP image.')
      return
    }
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarError('That image is too large (max 2 MB).')
      return
    }
    setAvatarFile(file)
    setAvatarPreview(URL.createObjectURL(file)) // instant preview, nothing uploaded yet
  }

  function cancelAvatarSelection() {
    setAvatarFile(null)
    setAvatarPreview(null)
    setAvatarError('')
  }

  async function handleAvatarUpload() {
    if (!avatarFile) return
    setUploading(true)
    setAvatarError('')
    try {
      const formData = new FormData()
      formData.append('image', avatarFile)
      const res = await api.put('/me/avatar', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      // updating the shared user means the Navbar avatar changes instantly
      updateUser({ avatar_url: res.data.avatar_url })
      cancelAvatarSelection()
      showToast('Profile picture updated')
    } catch (err) {
      showToast(err.response?.data?.error || 'Could not upload your photo. Try again.', 'error')
    } finally {
      setUploading(false)
    }
  }

  // ---------- Section 2: edit profile ----------
  async function saveProfile(vals) {
    try {
      const res = await api.put('/me', { name: vals.name.trim(), email: vals.email.trim() })
      // use the server's saved values (trimmed / lowercased email)
      setProfileValues({ name: res.data.name, email: res.data.email })
      updateUser({ name: res.data.name, email: res.data.email })
      showToast('Profile updated successfully')
    } catch (err) {
      if (err.response?.status === 409) {
        // "email already taken" belongs next to the email field, not in a toast
        profileForm.setFieldError('email', err.response.data?.error || 'Email already in use')
      } else {
        showToast(err.response?.data?.error || 'Could not update your profile', 'error')
      }
    }
  }

  // ---------- Section 3: change password ----------
  async function savePassword(vals) {
    try {
      await api.put('/me/password', vals)
      passwordForm.reset() // clears all three fields
      showToast('Password changed successfully')
    } catch (err) {
      const status = err.response?.status
      const message = err.response?.data?.error
      if (status === 401) {
        passwordForm.setFieldError('current_password', 'Current password is incorrect')
      } else if (status === 400 && message === 'Passwords do not match') {
        passwordForm.setFieldError('confirm_password', message)
      } else if (status === 400 && message === 'Min 6 characters') {
        passwordForm.setFieldError('new_password', 'Must be at least 6 characters')
      } else {
        showToast(message || 'Could not change your password', 'error')
      }
    }
  }

  // ---------- render ----------
  if (loadError) {
    return (
      <div className="page">
        <h1>My Profile</h1>
        <p className="error-text">{loadError}</p>
        <button className="btn btn-secondary" onClick={() => setReloadKey(k => k + 1)}>Try again</button>
      </div>
    )
  }
  if (!profile) {
    return <div className="page"><p>Loading profile...</p></div>
  }

  return (
    <div className="page">
      <h1>My Profile</h1>

      <div className="profile-sections">
        {/* Section 1 - profile picture */}
        <section className="profile-card">
          <h2>Profile Picture</h2>
          <div className="avatar-section">
            <Avatar
              name={user?.name}
              avatarUrl={user?.avatar_url}
              previewSrc={avatarPreview}
              size={112}
            />
            <div className="avatar-info">
              <strong>{user?.name}</strong>
              <span className="profile-meta">{user?.email}</span>
              {profile.created_at && (
                <span className="profile-meta">Member since {formatMemberSince(profile.created_at)}</span>
              )}
            </div>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/png, image/jpeg, image/webp"
            onChange={handleFileChange}
            style={{ display: 'none' }}
            aria-label="Choose a profile photo"
          />

          <div className="avatar-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              Change Photo
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleAvatarUpload}
              disabled={!avatarFile || uploading}
            >
              {uploading ? 'Uploading...' : 'Upload'}
            </button>
            {avatarFile && !uploading && (
              <button type="button" className="btn btn-link" onClick={cancelAvatarSelection}>
                Cancel
              </button>
            )}
          </div>
          {avatarFile && <p className="form-hint">Previewing {avatarFile.name}. Click Upload to save it.</p>}
          {avatarError && <p className="field-error" role="alert">{avatarError}</p>}
          {!avatarFile && !avatarError && <p className="form-hint">PNG, JPG or WEBP, up to 2 MB.</p>}
        </section>

        {/* Section 2 - edit profile */}
        <section className="profile-card">
          <h2>Edit Profile</h2>
          <form onSubmit={profileForm.handleSubmit(saveProfile)} noValidate>
            <Field
              label="Name" name="name" autoComplete="name"
              value={profileForm.values.name}
              onChange={profileForm.handleChange}
              error={profileForm.errors.name}
            />
            <Field
              label="Email" name="email" type="email" autoComplete="email"
              value={profileForm.values.email}
              onChange={profileForm.handleChange}
              error={profileForm.errors.email}
            />
            <button className="btn btn-primary" disabled={profileForm.isSubmitting}>
              {profileForm.isSubmitting ? 'Saving...' : 'Save Changes'}
            </button>
          </form>
        </section>

        {/* Section 3 - change password */}
        <section className="profile-card">
          <h2>Change Password</h2>
          <form onSubmit={passwordForm.handleSubmit(savePassword)} noValidate>
            <Field
              label="Current Password" name="current_password" type="password"
              autoComplete="current-password"
              value={passwordForm.values.current_password}
              onChange={passwordForm.handleChange}
              error={passwordForm.errors.current_password}
            />
            <Field
              label="New Password" name="new_password" type="password"
              autoComplete="new-password"
              value={passwordForm.values.new_password}
              onChange={passwordForm.handleChange}
              error={passwordForm.errors.new_password}
            />
            <PasswordStrengthMeter password={passwordForm.values.new_password} />
            <Field
              label="Confirm New Password" name="confirm_password" type="password"
              autoComplete="new-password"
              value={passwordForm.values.confirm_password}
              onChange={passwordForm.handleChange}
              error={passwordForm.errors.confirm_password}
            />
            <button className="btn btn-primary" disabled={passwordForm.isSubmitting}>
              {passwordForm.isSubmitting ? 'Updating...' : 'Update Password'}
            </button>
          </form>
        </section>

        {/* Account activity summary */}
        <section className="profile-card">
          <h2>Account Activity</h2>
          {statsError ? (
            <p className="error-text">{statsError}</p>
          ) : !stats ? (
            <p className="form-hint">Loading activity...</p>
          ) : (
            <div className="stat-grid">
              <div className="stat-card stat-card-orders">
                <div className="stat-label">Total Orders</div>
                <div className="stat-value">{stats.total_orders}</div>
              </div>
              <div className="stat-card stat-card-revenue">
                <div className="stat-label">Total Spent</div>
                <div className="stat-value">${stats.total_spent.toFixed(2)}</div>
              </div>
            </div>
          )}
        </section>

        {/* Danger zone - delete account */}
        <section className="profile-card danger-zone">
          <h2>Danger Zone</h2>
          <p className="form-hint">
            Deleting your account permanently removes your profile, order history,
            ratings and wishlist. This cannot be undone.
          </p>
          <button type="button" className="btn btn-danger" onClick={() => setShowDeleteModal(true)}>
            Delete Account
          </button>
        </section>
      </div>

      <ConfirmModal
        open={showDeleteModal}
        title="Delete your account?"
        message="This permanently deletes your profile, order history, ratings and wishlist. This action cannot be undone."
        confirmLabel="Yes, Delete My Account"
        danger
        loading={deleting}
        onConfirm={handleDeleteAccount}
        onCancel={() => setShowDeleteModal(false)}
      />
    </div>
  )
}
