CREATE DATABASE IF NOT EXISTS ecommerce;
USE ecommerce;

DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS product_images;
DROP TABLE IF EXISTS ratings;
DROP TABLE IF EXISTS wishlist;
DROP TABLE IF EXISTS coupons;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    email        VARCHAR(100) NOT NULL UNIQUE,
    password     VARCHAR(255) NOT NULL,
    role         ENUM('admin','customer') DEFAULT 'customer',
    avatar_url   VARCHAR(255) DEFAULT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE categories (
    id    INT AUTO_INCREMENT PRIMARY KEY,
    name  VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE products (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    name           VARCHAR(150) NOT NULL,
    description    TEXT,
    price          DECIMAL(10,2) NOT NULL,
    stock          INT NOT NULL DEFAULT 0,
    category_id    INT,
    image_url      VARCHAR(255),
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE TABLE product_images (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    product_id  INT NOT NULL,
    image_url   VARCHAR(255) NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE orders (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    user_id          INT NOT NULL,
    total_amount     DECIMAL(10,2) NOT NULL,
    status           ENUM('Pending','Confirmed','Shipped','Delivered','Cancelled') DEFAULT 'Pending',
    address          TEXT NOT NULL,
    coupon_code      VARCHAR(30) DEFAULT NULL,
    discount_amount  DECIMAL(10,2) DEFAULT 0.00,
    ordered_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE order_items (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    order_id    INT NOT NULL,
    product_id  INT NOT NULL,
    quantity    INT NOT NULL,
    unit_price  DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE ratings (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    product_id  INT NOT NULL,
    rating      TINYINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review      TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_product_rating (user_id, product_id)
);

CREATE TABLE wishlist (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    product_id  INT NOT NULL,
    added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE KEY unique_user_product_wishlist (user_id, product_id)
);

CREATE TABLE coupons (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    code             VARCHAR(30) NOT NULL UNIQUE,
    discount_percent INT NOT NULL CHECK (discount_percent BETWEEN 1 AND 100),
    active           BOOLEAN DEFAULT TRUE,
    expires_at       DATE DEFAULT NULL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO coupons (code, discount_percent, active, expires_at) VALUES
    ('WELCOME10', 10, TRUE, NULL),
    ('SAVE20', 20, TRUE, '2026-12-31');

CREATE TABLE notifications (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    message     VARCHAR(255) NOT NULL,
    type        ENUM('order','info','alert') DEFAULT 'info',
    is_read     BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);


