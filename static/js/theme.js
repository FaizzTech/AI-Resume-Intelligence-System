const toggleBtn = document.getElementById("toggle-btn");

toggleBtn.addEventListener("click", () => {
    document.body.classList.toggle("dark-mode");

    // store theme preference
    localStorage.setItem("theme", 
        document.body.classList.contains("dark-mode") ? "dark" : "light"
    );
});

// load saved theme
if (localStorage.getItem("theme") === "dark") {
    document.body.classList.add("dark-mode");
}
