import Tab from "./Tab";

export default function TabNav(props) {
  function cliTab() {
    props.setTab("cli");
  }

  function browseTab() {
    props.setTab("browser");
  }

  return (
    <>
      <Tab
        title="CLI"
        onClick={cliTab}
        activeTab={props.tab}
      />
      <Tab
        title="BROWSER"
        onClick={browseTab}
        activeTab={props.tab}
      />
    </>
  );
}