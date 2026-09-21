import React from "react";
import { useAuth } from "@/lib/auth";
import "./landing.css";

const FAQ = [
  ["I've already tried an accent app. What's different about Pronounce This?",
   "Other accent apps are primarily built for ESL learners. Pronounce This is designed specifically for non-U.S. actors — not just learning how to pronounce words correctly, but applying the accent to your scene. You get a reference for how your dialogue sounds in an American accent, and the other character's lines ready to download. Use the recording to run lines and practice, or let it be the reader for you when you film your audition."],
  ["Do I still need a dialect coach?",
   "Working with a dialect coach on your scene is great for immediate feedback. Pronounce This is great when you don't have the time or the budget to work with a dialect coach on every audition — an excellent resource to make sure your pronunciation is correct before you film your next scene."],
  ["How fast can I actually prep the accent before a self-tape audition?",
   "Paste your scene in and the breakdown is immediate — IPA, sound lists, and downloadable audio for both your lines and your reader's. It's that fast."],
  ["How does the reader's line work?",
   "Upload your scene, choose your character, then choose a male or female voice for the reader. Download the reader's lines — it pauses when your character is speaking, so it's timed to the scene."],
  ["What happens after the free trial?",
   "Once you've looked up your 5 free words and used your one free scene upload, you'll have the option to sign up for our monthly or annual plan. Choose whichever works for you, then keep using Pronounce This."],
];

const TRIED = [
  ["Hiring a dialect coach for one session", "Useful — but there's not always time or budget to book a session with a dialect coach before every audition."],
  ["A generic English pronunciation app", "Built for ESL speakers, not actors. It doesn't upload your scene and give you all of your dialogue spoken back as a reference, and it doesn't include the names, locations, and other words that come up in your dialogue."],
  ["Watching YouTube videos", "It might help you with the accent, but it won't help you apply the accent to your actual lines."],
  ["Guessing and hoping the accent sounds accurate", "All it takes is one mispronounced name or word to cost you the role."],
];

export default function LandingPage() {
  const { openPaywall, openLogin } = useAuth();
  const tryFree = () => openPaywall("trial");

  return (
    <div className="landing" data-testid="landing-page">
      <div className="hero">
        <div className="wrap">
          <div className="top-bar">
            <button type="button" className="link-quiet" onClick={openLogin} data-testid="landing-signin">Already a member? Sign in</button>
          </div>
          <h1>Pronounce This<span className="dot">.</span></h1>
          <p className="lede">An American accent pronunciation tool built for actors.</p>
          <div className="cta-row">
            <button type="button" className="btn" onClick={tryFree} data-testid="landing-cta-hero">Try Pronounce This.</button>
          </div>
          <div className="slug slug--pre-shot">Int. Your Next U.S. Audition</div>
          <div className="device-mockup device-mockup--shot" aria-hidden="true">
            <img src="/landing/hero-devices.jpg" alt="" />
          </div>
        </div>
      </div>

      <div className="breakdown">
        <div className="wrap">
          <div className="breakdown-slug">Casting Breakdown — Seeking</div>
          <div className="section-head"><h2>For the non-U.S. actor who…</h2></div>
          <div className="breakdown-single">
            <ul>
              <li>Booked a role and want to know if you're pronouncing your dialogue correctly</li>
              <li>Has a self-tape audition or a scene to prepare for acting class and needs to check their American pronunciation</li>
              <li>Got a self-tape audition and needs a reader</li>
              <li>Is learning the American accent and needs help with their American pronunciation</li>
            </ul>
          </div>
          <div className="breakdown-cta">
            <p>Let's get ready for your next U.S. role.</p>
            <button type="button" className="btn" onClick={tryFree} data-testid="landing-cta-breakdown">Try Pronounce This.</button>
          </div>
        </div>
      </div>

      <div className="struggle" id="struggle">
        <div className="wrap">
          <div className="section-head">
            <h2>You've got the audition. Your accent isn't there yet.</h2>
            <p>Imagine you get an audition and you don't have time to work with a dialect coach. You need to check your American pronunciation fast.</p>
          </div>
          <div className="script-page">
            <div className="tried tried--needs">
              <div className="tried-row"><div className="why">Your script has a character name, location or word that isn't in any dictionary, and you need to know: am I pronouncing it correctly?</div></div>
              <div className="tried-row"><div className="why">You need a place to listen and rehearse with a reference of your dialogue spoken in a standard American accent.</div></div>
              <div className="tried-row"><div className="why">You need a tool to record lines with you, or be your reader when you're ready to film your audition.</div></div>
            </div>
            <p className="script-lede">You know the feeling: you get the audition, the self-tape is due, and you're not sure if you're pronouncing all the words correctly.</p>
            <div className="tried">
              {TRIED.map(([what, why]) => (
                <div className="tried-row" key={what}>
                  <div className="what">{what}</div>
                  <div className="why">{why}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="scenes" id="scenes">
        <div className="wrap">
          <div className="section-head"><h2>Ways to use Pronounce This.</h2></div>
          <div className="scene-card">
            <div className="shot-frame shot-frame--second">
              <img src="/landing/word-tool.jpg" alt='Pronounce This Word tool showing the pronunciation of "server"' />
            </div>
            <div>
              <div className="scene-slug">Pronounce a word</div>
              <h3>Type any word, name, or location</h3>
              <p>Type a word, name or location and hear how it's pronounced, see it spelled phonetically, and hear real speakers on YouTube say the word.</p>
              <ul>
                <li>Instant IPA transcription for any word, name, or place</li>
                <li>Hear it spoken in an American accent</li>
                <li>Watch real people say it, in their own voices</li>
              </ul>
            </div>
          </div>
          <div className="scene-card">
            <div>
              <div className="scene-slug">Pronounce your scene</div>
              <h3>Hear your dialogue spoken in the American accent</h3>
              <p>Got an audition or working on a role? Upload your scene, choose your character, and hear it read back in the accent, word by word.</p>
              <ul>
                <li>See each word transcribed in American IPA</li>
                <li>Practice with sound lists pulled straight from your scene</li>
                <li>Download the audio of your character's dialogue for additional practice</li>
                <li>Download the other character's lines — run lines with it, or use it as your reader while you film your self-tape</li>
              </ul>
            </div>
            <div className="shot-frame">
              <img src="/landing/scene-tool.jpg" alt="Pronounce your scene tool showing a scene with lines transcribed in IPA and sound lists" />
            </div>
          </div>
        </div>
      </div>

      <div className="testimonial">
        <div className="wrap">
          <blockquote>"…this is actually incredible! What a game changer!"</blockquote>
        </div>
      </div>

      <div className="faq">
        <div className="wrap">
          <div className="section-head">
            <h2>Got a question?</h2>
            <p>Get your questions answered about Pronounce This.</p>
          </div>
          <div className="faq-list">
            {FAQ.map(([q, a]) => (
              <details className="faq-item" key={q}>
                <summary>{q}</summary>
                <p>{a}</p>
              </details>
            ))}
          </div>
        </div>
      </div>

      <div className="closing">
        <div className="wrap">
          <h2>Get ready for your next role<span className="dot">.</span></h2>
          <p>Bring your scene. Leave knowing exactly how it sounds in an American accent.</p>
          <button type="button" className="btn" onClick={tryFree} data-testid="landing-cta-closing">Try Pronounce This.</button>
        </div>
      </div>

      <footer>Pronounce This — an American accent pronunciation tool for actors</footer>
    </div>
  );
}
