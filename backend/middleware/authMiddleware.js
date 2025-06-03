// backend/middleware/authMiddleware.js
const jwtUtil = require('../utils/jwt');

const authenticateToken = (req, res, next) => {
    const authHeader = req.headers['authorization'];
    const token = authHeader && authHeader.split(' ')[1];

    if (token == null) {
        return res.status(401).json({ message: 'Authentication token missing' });
    }

    console.log(token);
    console.log(process.env.JWT_SECRET);
    

    jwtUtil.verifyToken(token, process.env.JWT_SECRET, (err, user) => {
        if (err) {
            console.error('JWT Verification Error:', err);
            return res.status(403).json({ message: 'Invalid or expired token' });
        }
        req.user = user; // Attach the decoded user payload to the request
        next();
    });
};

const authorizeRoles = (roles) => {
    return (req, res, next) => {
        if (req.user && roles.includes(req.user.role)) {
            next();
        } else {
            return res.status(403).json({ message: 'Unauthorized: Insufficient role' });
        }
    };
};

module.exports = { authenticateToken, authorizeRoles };