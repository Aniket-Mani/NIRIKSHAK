
const mongoose = require('mongoose');

// 1. Connect to MongoDB (optimized settings)
mongoose.connect('mongodb://localhost:27017/smart', {
  maxPoolSize: 50,
  socketTimeoutMS: 60000
})
.then(() => console.log(' MongoDB connected '))
.catch(err => {
  console.error('Connection failed:', err);
  process.exit(1);
});

// 2. Define schema (with duplicate protection)
const courseSubjectSchema = new mongoose.Schema({
  course: {
    type: String,
    required: true,
    uppercase: true,
    trim: true
  },
  semester: {
    type: Number,
    required: true,
    min: 1,
    max: 6
  },
  subject: {
    type: String,
    required: true,
    trim: true
  },
  subjectCode: {
    type: String,
    required: true,
    uppercase: true,
    trim: true,
    unique: true // Prevents duplicates
  }
}, { 
  versionKey: false // Disables __v field 
});

const CourseSubject = mongoose.model('CourseSubject', courseSubjectSchema);

// Complete course data
const courseStructure = {
  MCA: {
     1: {
     "CA711": "Problem Solving and Programming",
      "CA713": "Mathematical Foundations of Computer Applications",
      "CA715": "Digital Logic and Computer Organization",
      "CA717": "Data Structures and Applications",
      "CA719": "Operating Systems",
      "CA701": "Problem Solving Lab using Python",
      "CA703": "Data Structures Lab using C"
    },
    2: {
      "CA710": "Design and Analysis of Algorithms",
      "CA712": "Database Management Systems",
      "CA714": "Probability and Statistical Methods",
      "CA716": "Object-oriented Programming",
      "CA718": "Computer Networks",
      "CA702": "DBMS Lab",
      "CA704": "Computer Networks Lab",
      "INTERN": "Internship"
    },
    3: {
      "CA721": "Machine Learning Techniques",
      "CA723": "Computational Intelligence",
      "CA725": "Software Engineering",
      "CA727": "Accounting and Financial Management",
      "CA7A": "Elective-I",
      "CA705": "Machine Learning Lab",
      "CA707": "Business Communication",
      "CA709": "Computational Intelligence Lab"
     },
    4: {
      "CA720": "Deep Learning and Its Applications",
      "CA722": "Web Technology and Its Applications",
      "CA724": "Distributed and Cloud Computing",
      "CA7B": "Elective-II",
      "CA7C": "Elective-III",
      "CA706": "Deep Learning Lab",
      "CA708": "Distributed and Cloud Computing Lab",
      "INTERN": "Internship"
    },
    5: {
      "CA731": "Cyber Security",
      "CA733": "Mobile Applications Development",
      "CA735": "Organizational Behavior",
      "CA7D": "Elective-IV",
      "CA7E": "Elective-V",
      "CA70A": "Cyber Security Lab",
      "CA70B": "Mobile Applications Development Lab",
      "CA749": "Project Work Phase I"
    },
    6: {
      "CA750": "Project Work Phase II"
    }
  },
  MSC_CS: {
    1: {
      "CAS711": "Mathematical Foundations of Computer Science",
      "CAS713": "Networking Technologies",
      "CAS715": "Data Structures and Algorithms",
      "CAS717": "Problem Solving using Python and R",
      "CAS719": "Operating Systems Fundamentals",
      "CAS701": "Data Structures Lab",
      "CAS703": "Python and R Lab"
    },
    2: {
      "CAS712": "Computer Organization and Architecture",
      "CAS714": "Theory of Computation",
      "CAS716": "Advanced Statistical Techniques for Data Science",
      "CAS718": "DBMS and Data Mining",
      "CAS7AX": "Elective I",
      "CAS702": "FOSS Lab",
      "CAS704": "DBMS and Data Mining Lab"
    },
    3: {
      "CAS721": "Web Computing",
      "CAS723": "Artificial Intelligence and Machine Learning",
      "CAS725": "Object Oriented Software Engineering",
      "CAS7BX": "Elective II",
      "CAS7CX": "Elective III",
      "CAS705": "AI & ML Lab / Project Work Phase-I",
      "CAS749": "Project Work Phase-I"
    },
    4: {
      "CAS750": "Project Work Phase-II"
    }
  },
  MTech_CS: {
    1: {
      "CS601": "Mathematical Concepts of Computer Science",
      "CS603": "Advanced Data Structures and Algorithms",
      "CS605": "High Performance Computer Architecture",
      "CS607": "Principles of Machine Learning and Deep Learning",
      "E1": "Programme Elective I",
      "E2": "Programme Elective II",
      "CS609": "Computer System Design Lab"
    },
    2: {
      "CS602": "Service Oriented Architecture & Web Security",
      "CS604": "Advances in Operating Systems",
      "E3": "Programme Elective III",
      "E4": "Programme Elective IV",
      "E5": "Programme Elective V",
      "E6": "Programme Elective VI",
      "CS606": "Data Science and AI Lab",
      "CS608": "Web Development Lab"
    },
    3: {
      "CS677": "Project Work (Phase I)",
      "CS704": "Online Courses (NPTEL)"
    },
    4: {
      "CS678": "Project Work (Phase II)"
    }
   }
};

async function safeBulkInsert() {
  try {
    // Convert structure to document array
    const allCourses = [];
    for (const [program, semesters] of Object.entries(courseStructure)) {
      for (const [semesterStr, subjects] of Object.entries(semesters)) {
        const semester = Number(semesterStr);
        for (const [code, name] of Object.entries(subjects)) {
          allCourses.push({
            course: program,
            semester,
            subject: name,
            subjectCode: code
          });
        }
      }
    }

    console.log(`repared ${allCourses.length} courses for insertion`);

    // Insert with duplicate skipping
    const result = await CourseSubject.insertMany(allCourses, {
      ordered: false,  // Don't stop on errors
      lean: true       // Faster processing
    });

    console.log('\nInsertion Results:');
    console.log(`Successfully inserted: ${result.length} new courses`);
    console.log(`Skipped duplicates: ${allCourses.length - result.length}`);

  } catch (err) {
    if (err.writeErrors) {
      console.log(`${err.writeErrors.length} duplicates were automatically skipped`);
    } else {
      console.error('Unexpected error:', err.message);
    }
  } finally {
    await mongoose.disconnect();
    console.log('MongoDB connection closed');
  }
}

// 5. Run the insertion
safeBulkInsert();








