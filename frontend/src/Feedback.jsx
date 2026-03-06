import { useEffect, useState } from "react";

function Feedback() {

  const [emails, setEmails] = useState([]);

  useEffect(() => {
    fetch("https://phishing-backend-687412811667.asia-south1.run.app/api/low-confidence")
      .then(res => res.json())
      .then(data => setEmails(data));
  }, []);

  const sendFeedback = (email_id, label) => {

    fetch("https://phishing-backend-687412811667.asia-south1.run.app/api/submit-feedback", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        email_id: email_id,
        user_label: label
      })
    })
    .then(() => {
      alert("Feedback submitted");

      setEmails(emails.filter(e => e.email_id !== email_id));
    });
  };

  return (

    <div className="app">

      <h1>⚠️ Emails Needing Review</h1>

      {emails.map((email) => (

        <div key={email.email_id} className="review-card">

          <h3>{email.subject}</h3>

          <p>{email.content}</p>

          <p>Model Prediction: {email.prediction}</p>

          <p>Confidence: {(email.confidence * 100).toFixed(2)}%</p>

          <button onClick={() => sendFeedback(email.email_id, "Phishing")}>
            Mark Phishing
          </button>

          <button onClick={() => sendFeedback(email.email_id, "Legitimate")}>
            Mark Legitimate
          </button>

        </div>

      ))}

    </div>
  );
}

export default Feedback;