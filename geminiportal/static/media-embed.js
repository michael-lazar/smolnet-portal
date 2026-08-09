/* Click-to-embed for media links on gemini/spartan/scroll pages.
 *
 * The link_line macro renders media links with an [embed] toggle inside
 * the link line, followed after the line's <br/> by a hidden
 * div.media-embed containing the media element (img, audio, or video).
 * The media element has no src and fetches nothing until the toggle is
 * clicked and the src attribute is filled in.
 */
function toggleMedia(toggle) {
    var embed = toggle.nextElementSibling;
    while (!embed.classList.contains("media-embed")) {
        embed = embed.nextElementSibling;
    }
    var media = embed.firstElementChild;
    if (!media.src) {
        media.src = toggle.dataset.mediaUrl;
    }
    embed.hidden = !embed.hidden;
    toggle.textContent = embed.hidden ? "[embed]" : "[hide]";
    if (embed.hidden && media.pause) {
        media.pause();
    }
    return false;
}
