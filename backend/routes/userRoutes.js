const express = require('express');
const User = require('../models/User');

const router = express.Router();

router.get('/users', async (req, res) => {
  try {
    const users = await User.find({}, { password: 0 });
    res.status(200).json(users);
  } catch (err) {
    console.error('Error fetching users:', err);
    res.status(500).send({ message: 'Server error' });
  }
});

module.exports = router;
