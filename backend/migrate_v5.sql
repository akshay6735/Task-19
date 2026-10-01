-- Run this against your existing `ecommerce` database.
-- Adds the notifications table. Doesn't touch any existing data.
--
-- PowerShell:  Get-Content backend/migrate_v5.sql | mysql -u root -p ecommerce

USE ecommerce;

CREATE TABLE IF NOT EXISTS notifications (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    message     VARCHAR(255) NOT NULL,
    type        ENUM('order','info','alert') DEFAULT 'info',
    is_read     BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
