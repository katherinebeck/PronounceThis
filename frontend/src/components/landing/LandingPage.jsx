import React from "react";
import { useAuth } from "@/lib/auth";
import "./landing.css";

const FAQ = [
  ["I've already tried an accent app. What's different about Pronounce This?",
   "Other accent apps are primarily built for ESL learners. Pronounce This is designed specifically for non-U.S. actors. It's not just learning how to pronounce words correctly but applying the accent to your scene. You get a reference for how your dialogue sounds in an American accent and the other character's lines ready to download. Use the recording to run lines and practice or let it be the reader for you when you film your audition."],
  ["Do I still need a dialect coach?",
   "Working with a dialect coach on your scene is great for immediate feedback. Pronounce This is the perfect tool when you don't have the time or the budget to work with a dialect coach on every audition. It's an excellent resource to make sure your pronunciation is correct before you film your next scene."],
  ["How does the reader's line work?",
   "Upload your scene, choose your character, then choose a male or female voice for the reader. Download the reader's lines. You'll hear pauses when your character is speaking as it's timed to the scene."],
  ["How fast can I actually prep the accent before a self-tape audition?",
   "Paste your scene in and the breakdown is immediate. IPA transcription, sound lists and downloadable audio for both your lines and your reader's. It's that fast."],
  ["What happens after the free trial?",
   "Once you've looked up your 2 free words and used your one free scene upload, you'll have the option to sign up for our monthly or annual plan. Choose whichever works for you, then keep using Pronounce This."],
];

const TRIED = [
  ["Hiring a dialect coach for one session", "Useful, but there's not always time or budget to book a session with a dialect coach before every audition."],
  ["A generic English pronunciation app", "Built for ESL speakers, not actors. This is the first web app specifically designed for non-U.S. actors auditioning for roles requiring a Standard American accent."],
  ["Watching YouTube videos", "It might help you with the accent, but it won't help you apply the accent to your actual lines."],
  ["Guessing and hoping the accent sounds accurate", "All it takes is one mispronounced name or word to cost you the role."],
];

const TryButton = ({ onClick, testid, children = "Try Pronounce This" }) => (
  <button type="button" className="btn" onClick={onClick} data-testid={testid}>{children}</button>
);

export default function LandingPage() {
  const { openPaywall } = useAuth();
  const tryFree = () => openPaywall("trial");

  return (
    <div className="landing" data-testid="landing-page">
      <div className="topbar">
        <div className="wrap">
          <span className="member-q" data-testid="landing-member-q">Already a member?</span>
          <a href="/login" className="btn-login" data-testid="landing-signin">Log in</a>
        </div>
      </div>

      <section className="hero">
        <div className="wrap">
          <h1 className="logo-line">
            <img src="/landing/logo.png" alt="Pronounce This." className="logo" data-testid="landing-logo" />
          </h1>
          <p className="lede">An American accent pronunciation tool built for actors.</p>
          <div className="device-shot" aria-hidden="true">
            <img src="/landing/hero-devices.png" alt="" />
          </div>
          <TryButton onClick={tryFree} testid="landing-cta-hero" />
        </div>
      </section>

      <section className="breakdown">
        <div className="wrap">
          <h2>For the non-U.S. actor who…</h2>
          <div className="box">
            <ul>
              <li>Has a <strong>self-tape audition or a scene to prepare for acting class</strong> and needs to check their American pronunciation</li>
              <li><strong>Booked a role</strong> and want to know if you're pronouncing your dialogue correctly</li>
              <li>Got a self-tape audition and <strong>needs to run lines or needs 'a reader'</strong></li>
              <li>Is <strong>learning the American accent</strong> and needs help with their American pronunciation</li>
            </ul>
          </div>
          <TryButton onClick={tryFree} testid="landing-cta-breakdown" />
        </div>
      </section>

      <section className="struggle" id="struggle">
        <div className="wrap narrow">
          <h2 className="stack">You've got the audition.<br />Your accent isn't there yet…</h2>
          <p>Imagine you get an audition and you don't have time to work with a dialect coach. You need to check your American pronunciation fast.</p>
          <p>Your script has a character name, location or word that isn't in the dictionary, and you need to know: "Am I pronouncing it correctly?"</p>
          <p>You need your dialogue recorded so you can listen and repeat as you practice speaking your line in a standard American accent.</p>
          <p>You need to run lines and practice, and need a resource to help be your reader when you don't have anyone available to help you.</p>
          <hr />
          <h3>What are you going to do when you get the audition, the<br className="h3-break" />self-tape is due and you're not sure if you're pronouncing all the words correctly?</h3>
          <div className="tried">
            {TRIED.map(([what, why]) => (
              <div className="tried-row" key={what}>
                <div className="what">{what}</div>
                <div className="why">{why}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="ways" id="scenes">
        <div className="wrap">
          <h2 className="inline-logo-line">Ways to use <img src="/landing/logo@600.png" alt="Pronounce This." className="inline-logo" /></h2>
          <div className="feature">
            <div className="feature-text">
              <h3>Pronounce This Word</h3>
              <p>Type any word, name or location and hear how it's pronounced, see it spelled phonetically, and hear American speakers on YouTube say the word.</p>
              <ul>
                <li>Instant IPA transcription for any word, name, or place</li>
                <li>Hear it spoken in an American accent</li>
                <li>Watch real people say it, in their own voices</li>
              </ul>
            </div>
            <div className="feature-shot">
              <img src="/landing/word-tool.jpg?v=light" alt='Pronounce This Word tool showing the pronunciation of "server"' />
            </div>
          </div>
          <div className="feature feature--flip">
            <div className="feature-text">
              <h3>Pronounce This Scene</h3>
              <p>Got an audition or working on a role? Upload your scene, choose your character, and hear it spoken in the accent, word by word.</p>
              <ul>
                <li>See each word transcribed in American IPA</li>
                <li>Practice with sound lists pulled straight from your scene</li>
                <li>Download the audio of your character's dialogue for additional practice</li>
                <li>Download the other character's lines to run lines or, use it as your reader while you film your self-tape</li>
              </ul>
            </div>
            <div className="feature-shot">
              <img src="/landing/scene-tool.jpg?v=light" alt="Pronounce This Scene tool showing a scene with lines transcribed in IPA and sound lists" />
            </div>
          </div>
        </div>
      </section>

      <section className="preview">
        <div className="wrap narrow">
          <h3>Want to have a look inside of Pronounce This?<br />Get a sneak preview here.</h3>
          <div className="video" data-testid="landing-video">
            <video
              controls
              playsInline
              preload="metadata"
              poster="/landing/walkthrough-poster.jpg"
              title="A look inside Pronounce This"
            >
              <source src="/landing/walkthrough.mp4" type="video/mp4" />
              <source src="/landing/walkthrough.webm" type="video/webm" />
            </video>
          </div>
          <TryButton onClick={tryFree} testid="landing-cta-preview" />
        </div>
      </section>

      <section className="testimonial">
        <div className="wrap">
          <blockquote>"…this is actually incredible! What a game changer!"</blockquote>
        </div>
      </section>

      <section className="faq">
        <div className="wrap">
          <h2>Got a question?</h2>
          <p className="sub">Get your questions answered about Pronounce This.</p>
          <div className="faq-grid">
            {FAQ.map(([q, a]) => (
              <details className="faq-item" key={q}>
                <summary>{q}</summary>
                <p>{a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="closing">
        <div className="wrap">
          <h2>Get ready for your next role<span className="dot">.</span></h2>
          <p className="inline-logo-line">It's time to prepare for your next American accent audition with <img src="/landing/logo@600.png" alt="Pronounce This." className="inline-logo inline-logo--sm" /></p>
          <TryButton onClick={tryFree} testid="landing-cta-closing" />
        </div>
      </section>

      <footer>© {new Date().getFullYear()} Pronounce This — an American accent pronunciation tool for actors</footer>
    </div>
  );
}
