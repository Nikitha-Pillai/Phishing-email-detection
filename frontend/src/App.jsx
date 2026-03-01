import { useEffect, useState } from "react";
import "./App.css";

function App() {
  const [emails, setEmails] = useState([]);
  const [expandedIndex, setExpandedIndex] = useState(null);

  useEffect(() => {
    fetch("https://phishing-backend-687412811667.asia-south1.run.app/api/emails")
      .then((res) => res.json())
      .then((data) => setEmails(data))
      .catch((err) => console.error("Error fetching emails:", err));
  }, []);

  return (
    <div className="app">
      <h1 className="title">🛡️ AI Phishing Detection Dashboard</h1>

      <div className="table-container">
        {emails.length === 0 ? (
          <p className="empty">No emails found.</p>
        ) : (
          <table className="email-table">
            <thead>
              <tr>
                <th>Subject</th>
                <th>Prediction</th>
                <th>Confidence</th>
              </tr>
            </thead>

            <tbody>
              {emails.map((email, index) => (
                <>
                  <tr
                    key={index}
                    className={`row ${expandedIndex === index ? "active" : ""}`}
                    onClick={() =>
                      setExpandedIndex(expandedIndex === index ? null : index)
                    }
                  >
                    <td className="subject">
                      {email.subject || "No Subject"}
                    </td>

                    <td className="center">
                      <span
                        className={
                          email.prediction === "Phishing"
                            ? "badge phishing"
                            : "badge legit"
                        }
                      >
                        {email.prediction}
                      </span>
                    </td>

                    <td className="center confidence">
                      {email.confidence
                        ? (email.confidence * 100).toFixed(2)
                        : "0.00"}
                      %
                    </td>
                  </tr>

                  {expandedIndex === index && (
                    <tr className="expanded-row">
                      <td colSpan="3">
                        <strong>Email Body:</strong>
                        <p>{email.content}</p>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default App;