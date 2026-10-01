import { useEffect } from 'react'

/**
 * A small confirm/cancel dialog.
 *   open          - whether it's shown at all (renders nothing when false)
 *   title, message
 *   confirmLabel, cancelLabel
 *   danger        - styles the confirm button red, for destructive actions
 *   loading       - disables both buttons and swaps the confirm label mid-action
 *   onConfirm, onCancel
 */
export default function ConfirmModal({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  danger = false,
  loading = false,
  onConfirm,
  onCancel,
}) {
  // let Escape close it, same as clicking outside or the Cancel button
  useEffect(() => {
    if (!open) return
    function handleKey(e) {
      if (e.key === 'Escape' && !loading) onCancel()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, loading, onCancel])

  if (!open) return null

  return (
    <div className="modal-overlay" onClick={() => !loading && onCancel()}>
      <div
        className="modal-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
        onClick={e => e.stopPropagation()}
      >
        <h2 id="confirm-modal-title">{title}</h2>
        <p>{message}</p>
        <div className="modal-actions">
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={loading}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`}
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? 'Please wait...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
