// backend/utils/jwt.js
const jwt = require('jsonwebtoken');

const generateToken = (payload, secret, options = {}) => {
    return jwt.sign(payload, secret, options);
};

const verifyToken = (token, secret, callback) => {
    jwt.verify(token, secret, callback);
};

module.exports = { generateToken, verifyToken };